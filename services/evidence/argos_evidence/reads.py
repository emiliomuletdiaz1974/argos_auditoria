"""What the v1 API reads from the evidence of a campaign (ARG-077).

Nothing here writes. The chain is the one the dossier embeds —the same function builds both—, the
inclusion proof is computed from the same leaves the signed root was built from, and the credential
preview is the subject `issue_credential` would sign, taken from the same dossier.
"""

import json
from typing import Any

import psycopg

from argos_evidence.credential.issue import credential_record, credential_subject
from argos_evidence.dossier.build import evidence_chain
from argos_evidence.merkle import proof
from argos_evidence.roots import get_root, tree_for
from argos_evidence.worm import WormStore

__all__ = [
    "artifact_with_proof",
    "campaign_artifacts",
    "credential_preview",
    "credential_state",
    "current_dossier",
    "evidence_chain",
]

_ARTIFACTS = (
    "SELECT verdict_id::text, object_key, version_id, sha256, written_at FROM argos.evidence_index"
    " WHERE campaign_id = %(campaign)s"
    " AND (%(at)s::timestamptz IS NULL OR (written_at, verdict_id::text) < (%(at)s, %(id)s))"
    " ORDER BY written_at DESC, verdict_id DESC LIMIT %(limit)s"
)


def campaign_artifacts(
    dsn: str, campaign_id: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """The artifacts of a campaign, newest first; `id` and `created_at` are there for the cursor."""
    at, ident = after if after else (None, None)
    params = {"campaign": campaign_id, "at": at, "id": ident, "limit": limit}
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_ARTIFACTS, params).fetchall()
    return [
        {
            "verdict_id": row[0],
            "key": row[1],
            "version_id": row[2],
            "sha256": row[3],
            "id": row[0],
            "created_at": row[4].isoformat(),
        }
        for row in rows
    ]


def artifact_with_proof(dsn: str, store: WormStore, verdict_id: str) -> dict[str, Any] | None:
    """The artifact of a verdict and its place in the tree whose root the campaign signed."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id::text, object_key, version_id, sha256 FROM argos.evidence_index"
            " WHERE verdict_id = %s",
            (verdict_id,),
        ).fetchone()
        if row is None:
            return None
        leaves = conn.execute(
            "SELECT verdict_id::text, sha256 FROM argos.evidence_index WHERE campaign_id = %s",
            (row[0],),
        ).fetchall()
    campaign_id, key, version_id, sha256 = (str(value) for value in row)
    body = store.get(key, version_id)
    detail: dict[str, Any] = {
        "verdict_id": verdict_id,
        "campaign_id": campaign_id,
        "key": key,
        "version_id": version_id,
        "sha256": sha256,
        "artifact": json.loads(body),
        "proof": None,
    }
    root = get_root(dsn, campaign_id)
    if root is None:  # not rooted yet: the artifact exists, its proof does not
        return detail
    hashes = {str(leaf): bytes.fromhex(str(digest)) for leaf, digest in leaves}
    tree = tree_for(hashes)
    if tree.root.hex() != root.root:  # pragma: no cover - an index that disagrees with its root
        raise ValueError(f"the evidence index of {campaign_id} does not give its signed root")
    index = sorted(hashes).index(verdict_id)
    detail["proof"] = {
        "index": index,
        "size": tree.size,
        "root": root.root,
        "path": [[side, sibling.hex()] for side, sibling in proof(tree, index)],
    }
    return detail


def current_dossier(dsn: str, campaign_id: str) -> dict[str, Any] | None:
    """The newest dossier of a campaign: a late time stamp makes a new one, and it is this."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT sha256, json_key, json_version_id, pdf_key, pdf_version_id, created_at"
            " FROM argos.dossiers WHERE campaign_id = %s ORDER BY created_at DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "sha256": row[0],
        "json_key": row[1],
        "json_version_id": row[2],
        "pdf_key": row[3],
        "pdf_version_id": row[4],
        "created_at": row[5].isoformat(),
    }


def credential_preview(store: WormStore, dossier: dict[str, Any]) -> dict[str, Any]:
    """Exactly what the credential of this dossier would assert, before anyone signs it."""
    body = json.loads(store.get(str(dossier["json_key"]), str(dossier["json_version_id"])))
    return {
        "dossier_sha256": dossier["sha256"],
        "credentialSubject": credential_subject(body, str(dossier["sha256"])),
    }


def credential_state(dsn: str, store: WormStore, credential_id: str) -> dict[str, Any] | None:
    """A credential as it was issued, and whether its status bit says it is revoked."""
    record = credential_record(dsn, credential_id)
    if record is None:
        return None
    with psycopg.connect(dsn) as conn:
        revoked = conn.execute(
            "SELECT reason, revoked_by, revoked_at FROM argos.credential_revocations"
            " WHERE credential_id = %s",
            (credential_id,),
        ).fetchone()
    return {
        "credential_id": record.credential_id,
        "campaign_id": record.campaign_id,
        "dossier_sha256": record.dossier_sha256,
        "status_list": record.status_list,
        "status_index": record.status_index,
        "credential": json.loads(store.get(record.key, record.version_id)),
        "revoked": revoked is not None,
        "revocation": (
            None
            if revoked is None
            else {"reason": revoked[0], "by": revoked[1], "at": revoked[2].isoformat()}
        ),
    }
