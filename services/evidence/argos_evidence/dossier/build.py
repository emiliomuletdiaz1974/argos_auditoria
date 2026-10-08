"""The campaign dossier as canonical JSON (ARG-067, deviation note ARG-067).

Everything comes from records that already exist: the campaign and its seal,
the verdicts, the approvals, the findings, the texts drafted by the model with
their mark, and the evidence chain (artifacts, Merkle root, signature, time
stamp, journal report). Nothing in it depends on when it is assembled, so the
same state of a campaign always gives the same bytes and the same hash.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import psycopg
import yaml
from botocore.exceptions import ClientError

from argos_common.errors import ArgosError
from argos_evidence.core.integrity import canonical_instant, file_digest, seal_document
from argos_evidence.journal import report_key
from argos_evidence.roots import get_root
from argos_evidence.worm import WormAlreadyStoredError, WormStore
from argos_ontology.editorial.compiler import read_obligation
from argos_ontology.vocabulary import LIBRARY_DIR

SCHEMA = "argos/dossier/1"
RESULTS = ("compliant", "non_compliant", "not_demonstrated", "inconclusive")
SEVERITY_ORDER = ("critical", "high", "medium", "low")
CHALLENGE_CATALOG = LIBRARY_DIR / "challenges" / "catalog.yaml"


class DossierError(ArgosError):
    """The dossier cannot be assembled or rendered as asked."""


@dataclass(frozen=True)
class DossierRecord:
    campaign_id: str
    sha256: str
    json_key: str
    json_version_id: str
    pdf_key: str
    pdf_version_id: str


def _instant(value: dt.datetime | None) -> str | None:
    return None if value is None else canonical_instant(value)


def _campaign(conn: psycopg.Connection[Any], campaign_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id::text, name, status, scope, created_by, created_at, sealed_at, seal,"
        " snapshot_id::text, snapshot_hash, ontology_version, library_version, library_sha256"
        " FROM argos.campaigns WHERE id = %s",
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise DossierError(f"campaign {campaign_id} does not exist")
    if row[2] != "sealed":
        raise DossierError(
            f"campaign {campaign_id} is not sealed: only a closed campaign has a dossier"
        )
    return {
        "id": row[0],
        "name": row[1],
        "status": row[2],
        "scope": row[3],
        "created_by": row[4],
        "created_at": _instant(row[5]),
        "sealed_at": _instant(row[6]),
        "seal": row[7],
        "snapshot_id": row[8],
        "snapshot_hash": row[9],
        "ontology_version": row[10],
        "library_version": row[11],
        "library_sha256": row[12],
    }


def _results(conn: psycopg.Connection[Any], campaign_id: str) -> tuple[dict[str, Any], list[Any]]:
    rows = conn.execute(
        "SELECT obligation, result, count(*) FROM argos.verdicts WHERE campaign_id = %s"
        " GROUP BY obligation, result",
        (campaign_id,),
    ).fetchall()
    totals = dict.fromkeys(RESULTS, 0)
    per_obligation: dict[str, dict[str, int]] = {}
    for obligation, result, count in rows:
        totals[str(result)] += int(count)
        per_obligation.setdefault(str(obligation), dict.fromkeys(RESULTS, 0))[str(result)] += int(
            count
        )
    summary = {"units": sum(totals.values()), "by_result": totals}
    by_obligation = [{"obligation": o, **counts} for o, counts in sorted(per_obligation.items())]
    return summary, by_obligation


def _approvals(conn: psycopg.Connection[Any], campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT gate, approved_by, approved_at, approver_name FROM argos.approvals"
        " WHERE campaign_id = %s"
        " ORDER BY approved_at, gate, approved_by",
        (campaign_id,),
    ).fetchall()
    # The name is only there when it was recorded: a dossier assembled again from approvals made
    # before it existed stays the same, byte for byte.
    return [
        {"gate": g, "approved_by": b, "approved_at": _instant(a)}
        | ({"approver_name": n} if n else {})
        for g, b, a, n in rows
    ]


def _findings(
    conn: psycopg.Connection[Any], campaign_id: str, snapshot_id: str | None
) -> list[dict[str, Any]]:
    # The element a finding is about, by its name in the inventory the campaign measured
    # (2026-10-08): a person fixes `public.patients.ssn`, not a node key.
    rows = conn.execute(
        "SELECT f.id::text, f.challenge_id, f.obligation, f.severity, f.status, f.occurrences,"
        " f.system_id::text, coalesce(n.qualified_name, n.name)"
        " FROM argos.findings f LEFT JOIN argos.inventory_snapshot_nodes n"
        "   ON n.snapshot_id = %s::uuid AND n.node_key = f.node_key"
        " WHERE f.campaign_id = %s OR %s = ANY(f.campaigns_seen)",
        (snapshot_id, campaign_id, campaign_id),
    ).fetchall()
    findings = [
        {
            "id": r[0],
            "challenge_id": r[1],
            "obligation": r[2],
            "severity": r[3],
            "status": r[4],
            "occurrences": int(r[5]),
            "system_id": r[6],
        }
        | ({"element": r[7]} if r[7] else {})
        for r in rows
    ]
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["challenge_id"], f["id"]),
    )


def _texts(conn: psycopg.Connection[Any], campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, finding_id::text, body, generated, prompt_sha256 FROM argos.report_texts"
        " WHERE campaign_id = %s ORDER BY created_at, id",
        (campaign_id,),
    ).fetchall()
    return [
        {
            "kind": r[0],
            "finding_id": r[1],
            "body": r[2],
            "generated": bool(r[3]),
            "prompt_sha256": r[4],
        }
        for r in rows
    ]


def _journal_report(store: WormStore, campaign_id: str) -> dict[str, Any] | None:
    key = report_key(campaign_id)
    try:
        version_id = store.version_of(key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    return {"key": key, "version_id": version_id, "sha256": file_digest(store.get(key, version_id))}


def _chain(conn: psycopg.Connection[Any], dsn: str, store: WormStore, campaign_id: str) -> Any:
    artifacts = [
        {"verdict_id": r[0], "key": r[1], "version_id": r[2], "sha256": r[3]}
        for r in conn.execute(
            "SELECT verdict_id::text, object_key, version_id, sha256 FROM argos.evidence_index"
            " WHERE campaign_id = %s ORDER BY verdict_id::text",
            (campaign_id,),
        ).fetchall()
    ]
    root = get_root(dsn, campaign_id)
    merkle = (
        None
        if root is None
        else {
            "root": root.root,
            "leaf_count": root.leaf_count,
            "leaf_order": root.leaf_order,
            "tree_key": root.tree_key,
        }
    )
    signed = conn.execute(
        "SELECT object_key, version_id, sha256, key_id, non_production"
        " FROM argos.campaign_signatures WHERE campaign_id = %s",
        (campaign_id,),
    ).fetchone()
    signature = (
        None
        if signed is None
        else {
            "key": signed[0],
            "version_id": signed[1],
            "sha256": signed[2],
            "key_id": signed[3],
            "non_production": bool(signed[4]),
        }
    )
    stamp = None
    if signature is not None:
        row = conn.execute(
            "SELECT status, gen_time, policy, token_key FROM argos.tsa_queue WHERE object_key = %s",
            (signature["key"],),
        ).fetchone()
        if row is not None:
            stamp = {
                "status": row[0],
                "gen_time": _instant(row[1]),
                "policy": row[2],
                "token_key": row[3],
            }
    return {
        "artifacts": artifacts,
        "merkle": merkle,
        "signature": signature,
        "time_stamp": stamp,
        "journal_report": _journal_report(store, campaign_id),
    }


def evidence_chain(dsn: str, store: WormStore, campaign_id: str) -> Any:
    """The chain link by link, as the dossier embeds it: the API shows the same thing."""
    with psycopg.connect(dsn) as conn:
        return _chain(conn, dsn, store, campaign_id)


def _challenge_titles() -> dict[str, str]:
    if not CHALLENGE_CATALOG.is_file():
        return {}
    catalog = yaml.safe_load(CHALLENGE_CATALOG.read_text(encoding="utf-8")) or {}
    return {str(c["id"]): str(c["description"]) for c in catalog.get("challenges", [])}


def _labels(
    conn: psycopg.Connection[Any],
    campaign: dict[str, Any],
    findings: list[dict[str, Any]],
    by_obligation: list[dict[str, Any]],
) -> dict[str, Any]:
    """The names a person reads for the codes of this dossier, fixed when it is assembled.

    The PDF comes only from the JSON (deviation note ARG-067), so the titles of the challenges and
    the obligations and the names of the systems travel inside it, and only those it uses. A code
    whose name is not known has no label, and the PDF shows the code.
    """
    system_ids = sorted(
        {
            *((campaign.get("scope") or {}).get("system_ids") or []),
            *(f["system_id"] for f in findings),
        }
    )
    systems = {}
    if system_ids:
        rows = conn.execute(
            "SELECT id::text, name, kind FROM argos.systems WHERE id = ANY(%s::uuid[])",
            (system_ids,),
        ).fetchall()
        systems = {r[0]: {"name": r[1], "kind": r[2]} for r in rows}
    known = _challenge_titles()
    challenges = {c: known[c] for c in sorted({f["challenge_id"] for f in findings}) if c in known}
    obligations = {}
    codes = {
        str(o)
        for o in (*(f["obligation"] for f in findings), *(r["obligation"] for r in by_obligation))
    }
    for code in sorted(codes):
        spec = read_obligation(code)
        if spec is not None:
            obligations[spec.id] = {
                "title": spec.title,
                "norm": spec.norm,
                "article": spec.article,
                "summary": spec.summary or "",
            }
    return {"systems": systems, "challenges": challenges, "obligations": obligations}


def assemble(dsn: str, store: WormStore, campaign_id: str, verifier_url: str) -> bytes:
    """Canonical bytes of the dossier of a sealed campaign, with its own SHA-256."""
    with psycopg.connect(dsn) as conn:
        campaign = _campaign(conn, campaign_id)
        results, by_obligation = _results(conn, campaign_id)
        findings = _findings(conn, campaign_id, campaign["snapshot_id"])
        document = {
            "schema": SCHEMA,
            "campaign": campaign,
            "results": results,
            "results_by_obligation": by_obligation,
            "approvals": _approvals(conn, campaign_id),
            "findings": findings,
            "labels": _labels(conn, campaign, findings, by_obligation),
            "texts": _texts(conn, campaign_id),
            "evidence_chain": _chain(conn, dsn, store, campaign_id),
            "verification": {"verifier_url": verifier_url},
        }
    return seal_document(document)


def _keep(store: WormStore, key: str, body: bytes, retain_until: dt.datetime) -> str:
    try:
        return store.put_immutable(key, body, retain_until).version_id
    except WormAlreadyStoredError:
        version_id = store.version_of(key)
        if store.get(key, version_id) != body:
            raise DossierError(f"{key} is already stored with other bytes") from None
        return version_id


def write_dossier(
    dsn: str, store: WormStore, campaign_id: str, verifier_url: str, retain_until: dt.datetime
) -> DossierRecord:
    """Keep the JSON and the PDF of the current dossier. The same state gives the same record."""
    from argos_evidence.dossier.render import render_pdf

    body = assemble(dsn, store, campaign_id, verifier_url)
    digest = file_digest(body)
    base = f"campaigns/{campaign_id}/dossier/{digest}"
    json_version = _keep(store, f"{base}.json", body, retain_until)
    pdf_version = _keep(store, f"{base}.pdf", render_pdf(body, verifier_url), retain_until)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.dossiers"
            " (sha256, campaign_id, json_key, json_version_id, pdf_key, pdf_version_id)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (sha256) DO NOTHING",
            (digest, campaign_id, f"{base}.json", json_version, f"{base}.pdf", pdf_version),
        )
        row = conn.execute(
            "SELECT campaign_id::text, sha256, json_key, json_version_id, pdf_key, pdf_version_id"
            " FROM argos.dossiers WHERE sha256 = %s",
            (digest,),
        ).fetchone()
    if row is None:  # pragma: no cover - the insert above committed
        raise DossierError(f"the dossier {digest} was not recorded")
    return DossierRecord(*(str(v) for v in row))
