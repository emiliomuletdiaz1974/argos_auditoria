"""Activities of the evidence workflow (ARG-061…068): each one can run again without harm.

Every step writes to write-once places (WORM store, write-once tables) and
first looks for what an earlier attempt left, so a retry after a failure half
way ends with exactly the objects a clean run would have made.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Callable
from typing import Any

import psycopg
from temporalio import activity

from argos_common.release import Signer
from argos_evidence.artifacts import write_artifact
from argos_evidence.bundle import export_bundle
from argos_evidence.core.integrity import seal_document
from argos_evidence.credential.did import did_document
from argos_evidence.credential.issue import (
    issue_credential,
    revoke_credential,
    status_list_credential,
)
from argos_evidence.dossier import write_dossier
from argos_evidence.journal import journal_report
from argos_evidence.roots import get_root, record_root, tree_for
from argos_evidence.settings import EvidenceSettings
from argos_evidence.signing import sign_campaign_root, signature_key
from argos_evidence.tsa import Transport, process_queue, stamp_of
from argos_evidence.worm import WormAlreadyStoredError, WormIntegrityError, WormStore

ACTOR = "system:evidence"


def tree_key(campaign_id: str) -> str:
    return f"campaigns/{campaign_id}/merkle-tree.json"


class EvidenceActivities:
    def __init__(
        self,
        dsn: str,
        store: WormStore,
        signer: Signer,
        settings: EvidenceSettings,
        transport: Transport,
        tsa_roots_pem: list[str],
    ) -> None:
        self._dsn = dsn
        self._store = store
        self._signer = signer
        self._settings = settings
        self._transport = transport
        self._roots_pem = list(tsa_roots_pem)

    def _until(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC) + dt.timedelta(days=self._settings.RETENTION_DAYS)

    def _roots(self) -> list[Any]:
        from cryptography import x509

        return [x509.load_pem_x509_certificate(p.encode()) for p in self._roots_pem]

    # ---------- the steps, callable directly ----------

    def write_artifacts_now(self, campaign_id: str) -> int:
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT id::text FROM argos.verdicts WHERE campaign_id = %s ORDER BY id::text",
                (campaign_id,),
            ).fetchall()
        for (verdict_id,) in rows:
            write_artifact(self._dsn, self._store, campaign_id, verdict_id, self._until())
        return len(rows)

    def build_root_now(self, campaign_id: str) -> str:
        existing = get_root(self._dsn, campaign_id)
        if existing is not None:
            return existing.root
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT verdict_id::text, sha256 FROM argos.evidence_index WHERE campaign_id = %s",
                (campaign_id,),
            ).fetchall()
        leaves = {str(v): bytes.fromhex(str(h)) for v, h in rows}
        tree = tree_for(leaves)
        body = seal_document(
            {
                "schema": "argos/merkle-tree/1",
                "campaign_id": campaign_id,
                "leaf_order": "verdict_id",
                "leaves": [{"verdict_id": v, "sha256": leaves[v].hex()} for v in sorted(leaves)],
                "levels": [[node.hex() for node in level] for level in tree.levels],
                "root": tree.root.hex(),
            }
        )
        key = tree_key(campaign_id)
        try:
            self._store.put_immutable(key, body, self._until())
        except WormAlreadyStoredError:
            if self._store.get(key, self._store.version_of(key)) != body:
                raise WormIntegrityError(f"{key} holds another tree") from None
        record_root(self._dsn, campaign_id, tree, key)
        return tree.root.hex()

    def sign_root_now(self, campaign_id: str) -> str:
        record = sign_campaign_root(
            self._dsn, self._store, self._signer, campaign_id, None, self._until()
        )
        # The journal report is made from the head the signature fixed, so a retry, later and
        # with a longer journal, still writes the same report.
        head = json.loads(self._store.get(record.key, record.version_id))["payload"]["journal_head"]
        journal_report(self._dsn, self._store, campaign_id, head, self._until())
        return record.sha256

    def stamp_now(self, campaign_id: str) -> str:
        process_queue(self._dsn, self._store, self._transport, self._roots(), self._until())
        stamp = stamp_of(self._dsn, signature_key(campaign_id))
        return "missing" if stamp is None else stamp.status

    def write_dossier_now(self, campaign_id: str) -> str:
        record = write_dossier(
            self._dsn, self._store, campaign_id, self._settings.VERIFIER_URL, self._until()
        )
        return record.sha256

    def issue_credential_now(self, campaign_id: str, dossier_sha256: str) -> str:
        record = issue_credential(
            self._dsn,
            self._store,
            self._signer,
            self._settings.ISSUER_DID,
            self._settings.STATUS_BASE_URL,
            dossier_sha256,
            self._until(),
        )
        with psycopg.connect(self._dsn) as conn:
            older = conn.execute(
                "SELECT c.id FROM argos.credentials c"
                " LEFT JOIN argos.credential_revocations r ON r.credential_id = c.id"
                " WHERE c.campaign_id = %s AND c.id <> %s AND r.credential_id IS NULL",
                (campaign_id, record.credential_id),
            ).fetchall()
        for (credential_id,) in older:
            revoke_credential(
                self._dsn,
                str(credential_id),
                f"superseded by the credential of dossier {dossier_sha256}",
                ACTOR,
            )
        return record.credential_id

    @property
    def dsn(self) -> str:
        return self._dsn

    @property
    def store(self) -> WormStore:
        return self._store

    def stored(self, key: str, version_id: str) -> bytes:
        return self._store.get(key, version_id)

    def did_document(self) -> dict[str, Any]:
        return did_document(self._settings.ISSUER_DID, self._signer.public_key())

    def status_list(self, number: int) -> dict[str, Any]:
        return status_list_credential(
            self._dsn,
            self._signer,
            self._settings.ISSUER_DID,
            self._settings.STATUS_BASE_URL,
            number,
        )

    def bundle(self, dossier_sha256: str) -> dict[str, Any]:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT status_list FROM argos.credentials WHERE dossier_sha256 = %s",
                (dossier_sha256,),
            ).fetchone()
        return export_bundle(
            self._dsn,
            self._store,
            dossier_sha256,
            did_document=self.did_document(),
            status_list=self.status_list(int(row[0])) if row else None,
            tsa_roots_pem=self._roots_pem,
        )

    # ---------- the same steps as Temporal activities ----------

    @activity.defn(name="evidence_write_artifacts")
    async def write_artifacts(self, campaign_id: str) -> int:
        return await asyncio.to_thread(self.write_artifacts_now, campaign_id)

    @activity.defn(name="evidence_build_root")
    async def build_root(self, campaign_id: str) -> str:
        return await asyncio.to_thread(self.build_root_now, campaign_id)

    @activity.defn(name="evidence_sign_root")
    async def sign_root(self, campaign_id: str) -> str:
        return await asyncio.to_thread(self.sign_root_now, campaign_id)

    @activity.defn(name="evidence_stamp")
    async def stamp(self, campaign_id: str) -> str:
        return await asyncio.to_thread(self.stamp_now, campaign_id)

    @activity.defn(name="evidence_write_dossier")
    async def write_dossier(self, campaign_id: str) -> str:
        return await asyncio.to_thread(self.write_dossier_now, campaign_id)

    @activity.defn(name="evidence_issue_credential")
    async def issue_credential(self, campaign_id: str, dossier_sha256: str) -> str:
        return await asyncio.to_thread(self.issue_credential_now, campaign_id, dossier_sha256)

    def all(self) -> list[Callable[..., Any]]:
        return [
            self.write_artifacts,
            self.build_root,
            self.sign_root,
            self.stamp,
            self.write_dossier,
            self.issue_credential,
        ]
