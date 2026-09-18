"""ARG-067 · the dossier of a real sealed campaign: assembled from its records, kept in the WORM."""

import datetime as dt
import json
import os
import uuid
from typing import Any

import boto3
import httpx
import psycopg
import pytest
from cryptography import x509
from psycopg.types.json import Jsonb

from argos_challenges.evaluator import evaluate
from argos_challenges.findings import open_or_recur
from argos_challenges.seal import seal_campaign
from argos_challenges.store import create_campaign, persist_verdict
from argos_common.release import VaultTransitSigner
from argos_evidence.artifacts import write_artifact
from argos_evidence.core.integrity import file_digest, verify_artifact
from argos_evidence.dossier import DossierError, assemble, write_dossier
from argos_evidence.journal import anchor_head, journal_report
from argos_evidence.roots import record_root, tree_for
from argos_evidence.signing import sign_campaign_root
from argos_evidence.tsa import http_transport, process_queue
from argos_evidence.worm import WormStore, ensure_buckets

from .sources import register_catalog_system

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
TSA = os.environ.get("ARGOS_TEST_TSA", "http://127.0.0.1:3180")
URL = "https://verify.argos.example/check"


def _store() -> WormStore:
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7075",
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )
    ensure_buckets(client, default_retention_days=1)
    return WormStore(client)


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _campaign(dsn: str, store: WormStore) -> str:
    """A sealed campaign with two verdicts, a finding, a drafted summary and its evidence chain."""
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    campaign_id = create_campaign(dsn, "Campaña del expediente", {}, "user:campaign-manager")
    verdicts: dict[str, bytes] = {}
    for name, value in (("ok", "on"), ("ko", "off")):
        unit: dict[str, Any] = {
            "unit_id": uuid.uuid4().hex + uuid.uuid4().hex,
            "campaign_id": campaign_id,
            "challenge_id": f"sec-tls-{name}",
            "challenge_version": "1.0",
            "obligation": "OBL-RGPD-32-3",
            "system_id": system_id,
            "node_key": f"k-{name}",
            "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
            "sampling": None,
            "severity": "high",
        }
        verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": value}]}})
        verdict_id, _ = persist_verdict(dsn, campaign_id, unit, verdict, probe_journal_seq=3)
        if verdict.result == "non_compliant":
            open_or_recur(dsn, campaign_id, unit, verdict, verdict_id)
        record = write_artifact(dsn, store, campaign_id, verdict_id, _until())
        verdicts[verdict_id] = bytes.fromhex(record.sha256)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.report_texts (id, kind, campaign_id, body, prompt_sha256)"
            " VALUES (%s, 'summary', %s, %s, %s)",
            (
                str(uuid.uuid4()),
                campaign_id,
                Jsonb(
                    {"sections": [{"title": "Resumen", "body": "Dos unidades."}], "verdict_ids": []}
                ),
                "d" * 64,
            ),
        )
    seal_campaign(dsn, campaign_id)
    record_root(dsn, campaign_id, tree_for(verdicts), f"campaigns/{campaign_id}/tree.json")
    signer = VaultTransitSigner(VAULT, "root", key="argos-evidence")
    head = anchor_head(dsn)
    sign_campaign_root(dsn, store, signer, campaign_id, head, _until())
    journal_report(dsn, store, campaign_id, head, _until())
    return campaign_id


def _roots() -> list[x509.Certificate]:
    return [x509.load_pem_x509_certificate(httpx.get(f"{TSA}/ca.pem").content)]


def test_the_dossier_is_assembled_from_the_campaign_records(migrated_db: str) -> None:
    store = _store()
    campaign_id = _campaign(migrated_db, store)
    body = assemble(migrated_db, store, campaign_id, URL)
    assert verify_artifact(body)
    dossier = json.loads(body)
    assert dossier["campaign"]["id"] == campaign_id
    assert dossier["results"]["units"] == 2
    assert dossier["results"]["by_result"]["non_compliant"] == 1
    assert [f["challenge_id"] for f in dossier["findings"]] == ["sec-tls-ko"]
    assert dossier["texts"][0]["generated"] is True
    chain = dossier["evidence_chain"]
    assert len(chain["artifacts"]) == 2
    assert chain["merkle"]["leaf_count"] == 2
    assert chain["signature"]["non_production"] is True
    assert chain["time_stamp"]["status"] == "queued"
    assert chain["journal_report"]["key"].endswith("journal-report.json")


def test_the_same_state_gives_the_same_dossier(migrated_db: str) -> None:
    store = _store()
    campaign_id = _campaign(migrated_db, store)
    assert assemble(migrated_db, store, campaign_id, URL) == assemble(
        migrated_db, store, campaign_id, URL
    )


def test_an_unsealed_campaign_has_no_dossier(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Sin sellar", {}, "user:campaign-manager")
    with pytest.raises(DossierError, match="sealed"):
        assemble(migrated_db, _store(), campaign_id, URL)


def test_json_and_pdf_are_kept_and_a_late_stamp_makes_a_new_version(migrated_db: str) -> None:
    store = _store()
    campaign_id = _campaign(migrated_db, store)
    first = write_dossier(migrated_db, store, campaign_id, URL, _until())
    assert write_dossier(migrated_db, store, campaign_id, URL, _until()) == first
    body = store.get(first.json_key, first.json_version_id)
    assert file_digest(body) == first.sha256
    assert store.get(first.pdf_key, first.pdf_version_id).startswith(b"%PDF")

    process_queue(migrated_db, store, http_transport(TSA), _roots(), _until())
    second = write_dossier(migrated_db, store, campaign_id, URL, _until())
    assert second.sha256 != first.sha256
    stamped = json.loads(store.get(second.json_key, second.json_version_id))
    assert stamped["evidence_chain"]["time_stamp"]["status"] == "stamped"
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT sha256 FROM argos.dossiers WHERE campaign_id = %s", (campaign_id,)
        ).fetchall()
    assert {r[0] for r in rows} == {first.sha256, second.sha256}
