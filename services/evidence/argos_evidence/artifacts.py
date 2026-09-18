"""Evidence artifacts (ARG-062, deviation note ARG-062).

An artifact is the unit of proof: the minimised result of one probe with the
context an expert needs years later to understand it on its own. It is the
canonical JSON of the journal (same function, not a second one) and it carries
its own SHA-256, computed without that field, so it can be checked in
isolation. The SHA-256 of the whole file is what the index keeps and what
enters the campaign's Merkle tree.

The same verdict always gives the same bytes: the artifact carries when the
verdict was recorded, not when the artifact was written.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg

from argos_common.errors import ArgosError
from argos_common.journal import canonicalize
from argos_connector.validators import VALIDATORS
from argos_evidence.worm import WormAlreadyStoredError, WormIntegrityError, WormStore

SCHEMA = "argos/evidence/1"
KIND = "probe_evidence"
EVENT_SUBJECT = "argos.evidence.artifact_written"
EVENT_TYPE = "evidence.artifact_written.v1"

_PLATFORM_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # uuid
    r"|[0-9a-f]{32,}"  # digest
)
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[/-][A-Za-z0-9]+)*|[A-Za-z0-9]+")

_SELECT_VERDICT = (
    "SELECT id::text, campaign_id::text, unit_id, challenge_id, challenge_version, obligation,"
    " system_id::text, node_key, result, verdict, verdict_hash, probe_journal_seq, created_at"
    " FROM argos.verdicts WHERE id = %s AND campaign_id = %s"
)
_VERDICT_COLUMNS = (
    "id",
    "campaign_id",
    "unit_id",
    "challenge_id",
    "challenge_version",
    "obligation",
    "system_id",
    "node_key",
    "result",
    "verdict",
    "verdict_hash",
    "probe_journal_seq",
    "created_at",
)


class ArtifactNotMinimisedError(ArgosError):
    """The artifact would carry a value shaped like a personal identifier (P-16)."""


@dataclass(frozen=True)
class ArtifactRecord:
    campaign_id: str
    verdict_id: str
    key: str
    version_id: str
    sha256: str


def artifact_key(campaign_id: str, verdict_id: str) -> str:
    return f"campaigns/{campaign_id}/artifacts/{verdict_id}.json"


def canonical_instant(value: dt.datetime) -> str:
    """UTC with microseconds and a Z, the same shape as the journal."""
    if value.tzinfo is None:
        raise ValueError("the time must carry a time zone")
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _identifiers_in(text: str) -> bool:
    if _PLATFORM_ID.fullmatch(text.strip().lower()):
        return False
    candidates = {text.strip().upper(), *(t.upper() for t in _TOKEN.findall(text))}
    return any(check(c) for c in candidates for check in VALIDATORS.values())


def personal_identifiers(document: Any, path: str = "$") -> list[str]:
    """JSON paths of every string that holds a validated DNI, NIE, NUSS or Spanish IBAN."""
    if isinstance(document, str):
        return [path] if _identifiers_in(document) else []
    if isinstance(document, Mapping):
        return [p for k, v in document.items() for p in personal_identifiers(v, f"{path}.{k}")]
    if isinstance(document, list):
        return [p for i, v in enumerate(document) for p in personal_identifiers(v, f"{path}[{i}]")]
    return []


def build_artifact(row: Mapping[str, Any]) -> bytes:
    """Canonical bytes of the artifact of one verdict row, with its self-excluded hash."""
    verdict = row["verdict"]
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": KIND,
        "campaign_id": str(row["campaign_id"]),
        "verdict_id": str(row["id"]),
        "unit_id": str(row["unit_id"]),
        "challenge": {"id": str(row["challenge_id"]), "version": str(row["challenge_version"])},
        "obligation": str(row["obligation"]),
        "system_id": str(row["system_id"]),
        "node_key": str(row["node_key"]),
        "result": str(row["result"]),
        "via": verdict.get("via"),
        "detail": verdict.get("detail"),
        "verdict_hash": str(row["verdict_hash"]),
        "query_journal_seq": row["probe_journal_seq"],
        "evaluated_at": canonical_instant(row["created_at"]),
    }
    found = personal_identifiers(document)
    if found:
        raise ArtifactNotMinimisedError(
            f"the artifact would carry personal identifiers at {', '.join(found)}"
        )
    return seal_document(document)


def seal_document(document: Mapping[str, Any]) -> bytes:
    """Canonical bytes of ``document`` with its own SHA-256, computed without that field."""
    content = dict(document)
    content.pop("sha256", None)
    sealed = {**content, "sha256": file_digest(canonicalize(content).encode("utf-8"))}
    return canonicalize(sealed).encode("utf-8")


def file_digest(body: bytes) -> str:
    """SHA-256 of a stored file, as the index, the tree and the record name it."""
    return hashlib.sha256(body).hexdigest()


def verify_artifact(body: bytes) -> bool:
    """True when ``body`` is canonical and its inner hash matches the rest of it."""
    try:
        document = json.loads(body)
    except ValueError:
        return False
    if not isinstance(document, dict) or not isinstance(document.get("sha256"), str):
        return False
    try:
        if canonicalize(document).encode("utf-8") != body:
            return False
        content = canonicalize({k: v for k, v in document.items() if k != "sha256"})
    except ValueError:
        return False
    return file_digest(content.encode("utf-8")) == str(document["sha256"])


def _verdict_row(dsn: str, campaign_id: str, verdict_id: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_SELECT_VERDICT, (verdict_id, campaign_id)).fetchone()
    if row is None:
        raise LookupError(f"verdict {verdict_id} is not part of campaign {campaign_id}")
    return dict(zip(_VERDICT_COLUMNS, row, strict=True))


def _indexed(dsn: str, verdict_id: str) -> ArtifactRecord | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id::text, verdict_id::text, object_key, version_id, sha256"
            " FROM argos.evidence_index WHERE verdict_id = %s",
            (verdict_id,),
        ).fetchone()
    return None if row is None else ArtifactRecord(*(str(v) for v in row))


def write_artifact(
    dsn: str, store: WormStore, campaign_id: str, verdict_id: str, retain_until: dt.datetime
) -> ArtifactRecord:
    """Write the artifact of a verdict once, index it and return where it is.

    Idempotent: a retry finds the index row, or the stored object, and checks that
    its bytes are the ones this verdict produces.
    """
    body = build_artifact(_verdict_row(dsn, campaign_id, verdict_id))
    digest = hashlib.sha256(body).hexdigest()
    key = artifact_key(campaign_id, verdict_id)

    indexed = _indexed(dsn, verdict_id)
    if indexed is not None:
        if indexed.sha256 != digest:
            raise WormIntegrityError(f"the indexed artifact of {verdict_id} has another hash")
        return indexed

    try:
        version_id = store.put_immutable(key, body, retain_until).version_id
    except WormAlreadyStoredError:
        version_id = store.version_of(key)
        if hashlib.sha256(store.get(key, version_id)).hexdigest() != digest:
            raise WormIntegrityError(f"{key} is stored with other bytes") from None

    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.evidence_index"
            " (verdict_id, campaign_id, object_key, version_id, sha256)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (verdict_id) DO NOTHING",
            (verdict_id, campaign_id, key, version_id, digest),
        )
    record = _indexed(dsn, verdict_id)
    if record is None or record.sha256 != digest:  # pragma: no cover - only under a race
        raise WormIntegrityError(f"the index of {verdict_id} does not match its artifact")
    return record


async def announce_artifact(bus: Any, record: ArtifactRecord) -> None:
    """Publish the pointer on the EVIDENCE stream; the Merkle builder consumes it."""
    await bus.publish(
        EVENT_SUBJECT,
        EVENT_TYPE,
        {
            "campaign_id": record.campaign_id,
            "verdict_id": record.verdict_id,
            "key": record.key,
            "version_id": record.version_id,
            "sha256": record.sha256,
        },
    )
