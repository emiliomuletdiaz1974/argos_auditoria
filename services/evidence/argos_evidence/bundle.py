"""The verification bundle of a dossier: what is handed to a third party (ARG-069).

Plain JSON with the exact bytes, in base64, of what was handed over (the dossier,
the signed root envelope, the time stamp token, every artifact with its
inclusion proof) and the credential, next to what is public (the issuer's DID
document, the status list, the TSA roots). The public verifier needs nothing
else.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import psycopg

from argos_common.errors import ArgosError
from argos_evidence.core.integrity import file_digest
from argos_evidence.merkle import proof
from argos_evidence.roots import tree_for
from argos_evidence.worm import WormStore

BUNDLE_SCHEMA = "argos/verification-bundle/1"


class BundleError(ArgosError):
    """The dossier cannot be exported as asked."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def export_bundle(
    dsn: str,
    store: WormStore,
    dossier_sha256: str,
    *,
    did_document: Mapping[str, Any],
    status_list: Mapping[str, Any] | None,
    tsa_roots_pem: list[str],
) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        dossier_row = conn.execute(
            "SELECT campaign_id::text, json_key, json_version_id FROM argos.dossiers"
            " WHERE sha256 = %s",
            (dossier_sha256,),
        ).fetchone()
        if dossier_row is None:
            raise BundleError(f"there is no dossier {dossier_sha256}")
        campaign_id = str(dossier_row[0])
        signature = conn.execute(
            "SELECT object_key, version_id FROM argos.campaign_signatures WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()
        if signature is None:
            raise BundleError(f"campaign {campaign_id} has no signed root to export")
        stamp = conn.execute(
            "SELECT token_key, token_version_id FROM argos.tsa_queue"
            " WHERE object_key = %s AND status = 'stamped'",
            (signature[0],),
        ).fetchone()
        artifacts = conn.execute(
            "SELECT verdict_id::text, object_key, version_id, sha256 FROM argos.evidence_index"
            " WHERE campaign_id = %s ORDER BY verdict_id::text",
            (campaign_id,),
        ).fetchall()
        credential = conn.execute(
            "SELECT object_key, version_id FROM argos.credentials WHERE dossier_sha256 = %s",
            (dossier_sha256,),
        ).fetchone()

    dossier = store.get(str(dossier_row[1]), str(dossier_row[2]))
    if file_digest(dossier) != dossier_sha256:
        raise BundleError(f"the stored dossier {dossier_sha256} does not match its hash")
    tree = tree_for({str(r[0]): bytes.fromhex(str(r[3])) for r in artifacts})
    exported = []
    for index, (_, key, version, _digest) in enumerate(artifacts):
        exported.append(
            {
                "artifact": _b64(store.get(str(key), str(version))),
                "proof": {
                    "index": index,
                    "size": tree.size,
                    "path": [[side, sibling.hex()] for side, sibling in proof(tree, index)],
                    "root": tree.root.hex(),
                },
            }
        )
    return {
        "schema": BUNDLE_SCHEMA,
        "dossier": _b64(dossier),
        "root_signature": _b64(store.get(str(signature[0]), str(signature[1]))),
        "timestamp_token": _b64(store.get(str(stamp[0]), str(stamp[1]))) if stamp else None,
        "tsa_roots": list(tsa_roots_pem),
        "did_document": dict(did_document),
        "credential": (
            json.loads(store.get(str(credential[0]), str(credential[1]))) if credential else None
        ),
        "status_list": dict(status_list) if status_list is not None else None,
        "artifacts": exported,
    }
