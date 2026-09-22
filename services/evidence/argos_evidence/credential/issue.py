"""The verifiable credential of a campaign (ARG-068, ADR-0011).

A W3C VC 2.0 with an eddsa-jcs-2022 proof, issued by the operator's did:web,
that says which dossier (by its hash) closed which campaign, over which Merkle
root and library version, with what results. It carries no personal data and
no name of a client system: the subject is built from an explicit list of
fields. Revoking it never touches it: a bit goes up in the Bitstring Status
List, which is rebuilt from the revocations recorded, and signed again.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import psycopg

from argos_common.errors import ArgosError
from argos_common.journal_pg import PostgresJournal
from argos_common.release import Signer
from argos_evidence.artifacts import personal_identifiers
from argos_evidence.core.integrity import file_digest, verify_artifact
from argos_evidence.credential.did import verification_method
from argos_evidence.credential.proof import add_proof, jcs
from argos_evidence.credential.status import (
    LIST_SIZE,
    bitstring_with,
    encode_list,
)
from argos_evidence.worm import WormAlreadyStoredError, WormStore

VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
CREDENTIAL_TYPE = "ArgosCampaignCredential"
ACTOR = "system:evidence"
SUBJECT_KEYS = frozenset(
    {
        "id",
        "type",
        "campaignId",
        "dossierSha256",
        "merkleRoot",
        "sealedAt",
        "libraryVersion",
        "ontologyVersion",
        "units",
        "results",
        "findingsBySeverity",
        "nonProduction",
    }
)


class CredentialError(ArgosError):
    """The credential cannot be issued or revoked as asked."""


@dataclass(frozen=True)
class CredentialRecord:
    credential_id: str
    campaign_id: str
    dossier_sha256: str
    status_list: int
    status_index: int
    key: str
    version_id: str
    sha256: str


def _utc_seconds(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# What stays in the dossier and never travels in the credential: who approved, what was found and
# where, the drafted texts, the results per obligation and the artifacts themselves. Only counts,
# versions and hashes leave; the preview lists these so the reviewer sees what is left behind.
WITHHELD = (
    "approvals",
    "campaign.name",
    "evidence_chain.artifacts",
    "findings",
    "results_by_obligation",
    "texts",
)


def credential_subject(dossier: Mapping[str, Any], dossier_sha256: str) -> dict[str, Any]:
    """What the credential asserts, taken field by field from the dossier."""
    campaign = dossier["campaign"]
    chain = dossier.get("evidence_chain") or {}
    merkle = chain.get("merkle") or {}
    signature = chain.get("signature") or {}
    severities: dict[str, int] = {}
    for finding in dossier.get("findings", []):
        severities[str(finding["severity"])] = severities.get(str(finding["severity"]), 0) + 1
    subject = {
        "id": f"urn:argos:campaign:{campaign['id']}",
        "type": "ComplianceCampaign",
        "campaignId": str(campaign["id"]),
        "dossierSha256": dossier_sha256,
        "merkleRoot": merkle.get("root"),
        "sealedAt": campaign.get("sealed_at"),
        "libraryVersion": campaign.get("library_version"),
        "ontologyVersion": campaign.get("ontology_version"),
        "units": dossier["results"]["units"],
        "results": dict(dossier["results"]["by_result"]),
        "findingsBySeverity": dict(sorted(severities.items())),
        "nonProduction": bool(signature.get("non_production", True)),
    }
    found = personal_identifiers(subject)
    if found:  # the subject is built from identifiers and counts; this guards a future change
        raise CredentialError(f"the credential would carry personal data at {', '.join(found)}")
    return subject


def build_credential(
    *,
    credential_id: str,
    issuer: str,
    valid_from: str,
    subject: Mapping[str, Any],
    status_list_url: str,
    status_index: int,
) -> dict[str, Any]:
    return {
        "@context": [VC_CONTEXT],
        "id": credential_id,
        "type": ["VerifiableCredential", CREDENTIAL_TYPE],
        "issuer": issuer,
        "validFrom": valid_from,
        "credentialSubject": dict(subject),
        "credentialStatus": {
            "id": f"{status_list_url}#{status_index}",
            "type": "BitstringStatusListEntry",
            "statusPurpose": "revocation",
            "statusListIndex": str(status_index),
            "statusListCredential": status_list_url,
        },
    }


def status_list_credential_document(
    issuer: str, list_url: str, revoked: Iterable[int], valid_from: str
) -> dict[str, Any]:
    return {
        "@context": [VC_CONTEXT],
        "id": list_url,
        "type": ["VerifiableCredential", "BitstringStatusListCredential"],
        "issuer": issuer,
        "validFrom": valid_from,
        "credentialSubject": {
            "id": f"{list_url}#list",
            "type": "BitstringStatusList",
            "statusPurpose": "revocation",
            "encodedList": encode_list(bitstring_with(revoked)),
        },
    }


def credential_key(campaign_id: str, credential_id: str) -> str:
    return f"campaigns/{campaign_id}/credential/{credential_id.removeprefix('urn:uuid:')}.json"


_RECORD = (
    "SELECT id, campaign_id::text, dossier_sha256, status_list, status_index, object_key,"
    " version_id, sha256 FROM argos.credentials"
)


def _record(dsn: str, where: str, value: str) -> CredentialRecord | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(f"{_RECORD} WHERE {where} = %s", (value,)).fetchone()  # noqa: S608
    if row is None:
        return None
    return CredentialRecord(
        str(row[0]),
        str(row[1]),
        str(row[2]),
        int(row[3]),
        int(row[4]),
        str(row[5]),
        str(row[6]),
        str(row[7]),
    )


def credential_record(dsn: str, credential_id: str) -> CredentialRecord | None:
    return _record(dsn, "id", credential_id)


def issue_credential(
    dsn: str,
    store: WormStore,
    signer: Signer,
    issuer: str,
    status_base_url: str,
    dossier_sha256: str,
    retain_until: dt.datetime,
    now: dt.datetime | None = None,
) -> CredentialRecord:
    """Issue, once per dossier, the credential that points to it by its hash."""
    existing = _record(dsn, "dossier_sha256", dossier_sha256)
    if existing is not None:
        return existing
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id::text, json_key, json_version_id FROM argos.dossiers"
            " WHERE sha256 = %s",
            (dossier_sha256,),
        ).fetchone()
    if row is None:
        raise CredentialError(f"there is no dossier {dossier_sha256}")
    campaign_id, json_key, json_version = str(row[0]), str(row[1]), str(row[2])
    body = store.get(json_key, json_version)
    if file_digest(body) != dossier_sha256 or not verify_artifact(body):
        raise CredentialError(f"the stored dossier {dossier_sha256} does not match its hash")
    dossier = json.loads(body)
    if not (dossier.get("evidence_chain") or {}).get("signature"):
        raise CredentialError("a dossier whose root is not signed does not get a credential")

    with psycopg.connect(dsn) as conn:
        number = int(conn.execute("SELECT nextval('argos.credential_status_seq')").fetchone()[0])  # type: ignore[index]
    status_list, status_index = divmod(number, LIST_SIZE)
    credential_id = f"urn:uuid:{uuid.uuid4()}"
    issued_at = _utc_seconds(now or dt.datetime.now(dt.UTC))
    document = build_credential(
        credential_id=credential_id,
        issuer=issuer,
        valid_from=issued_at,
        subject=credential_subject(dossier, dossier_sha256),
        status_list_url=f"{status_base_url.rstrip('/')}/{status_list}",
        status_index=status_index,
    )
    credential = jcs(add_proof(document, signer, verification_method(issuer), issued_at))
    key = credential_key(campaign_id, credential_id)
    try:
        version_id = store.put_immutable(key, credential, retain_until).version_id
    except WormAlreadyStoredError:  # pragma: no cover - the id is fresh
        raise CredentialError(f"{key} already exists") from None

    digest = file_digest(credential)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.credentials (id, campaign_id, dossier_sha256, status_list,"
            " status_index, object_key, version_id, sha256)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                credential_id,
                campaign_id,
                dossier_sha256,
                status_list,
                status_index,
                key,
                version_id,
                digest,
            ),
        )
        PostgresJournal(dsn).append(
            ACTOR,
            "credential.issued",
            {
                "credential": credential_id,
                "campaign": campaign_id,
                "dossier": dossier_sha256,
                "sha256": digest,
            },
            conn=conn,
        )
    record = _record(dsn, "id", credential_id)
    if record is None:  # pragma: no cover - the insert above committed
        raise CredentialError(f"the credential {credential_id} was not recorded")
    return record


def revoke_credential(dsn: str, credential_id: str, reason: str, revoked_by: str) -> None:
    """Record a revocation. The credential itself does not change; its status bit does."""
    if not reason.strip():
        raise CredentialError("a revocation needs its reason")
    if _record(dsn, "id", credential_id) is None:
        raise CredentialError(f"there is no credential {credential_id}")
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.credential_revocations (credential_id, reason, revoked_by)"
            " VALUES (%s, %s, %s) ON CONFLICT (credential_id) DO NOTHING",
            (credential_id, reason, revoked_by),
        )
        PostgresJournal(dsn).append(
            revoked_by,
            "credential.revoked",
            {"credential": credential_id, "reason": reason},
            conn=conn,
        )


def status_list_credential(
    dsn: str,
    signer: Signer,
    issuer: str,
    status_base_url: str,
    status_list: int,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """The signed status list, rebuilt from the recorded revocations."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT c.status_index FROM argos.credential_revocations r"
            " JOIN argos.credentials c ON c.id = r.credential_id WHERE c.status_list = %s",
            (status_list,),
        ).fetchall()
    valid_from = _utc_seconds(now or dt.datetime.now(dt.UTC))
    document = status_list_credential_document(
        issuer,
        f"{status_base_url.rstrip('/')}/{status_list}",
        (int(r[0]) for r in rows),
        valid_from,
    )
    return add_proof(document, signer, verification_method(issuer), valid_from)
