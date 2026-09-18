"""ARG-062 · artifacts of a real verdict: written once to the WORM store and indexed."""

import datetime as dt
import hashlib
import uuid
from typing import Any

import boto3
import psycopg
import pytest

from argos_challenges.evaluator import evaluate
from argos_challenges.store import create_campaign, persist_verdict
from argos_evidence.artifacts import artifact_key, verify_artifact, write_artifact
from argos_evidence.worm import WormStore, ensure_buckets

from .sources import register_catalog_system

pytestmark = pytest.mark.integration

ENDPOINT = "http://127.0.0.1:7075"


def _store() -> WormStore:
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )
    ensure_buckets(client, default_retention_days=1)
    return WormStore(client)


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _verdict(dsn: str, observed: str = "off") -> tuple[str, str]:
    """A campaign under a fresh id (keys in the shared WORM store never collide) and one verdict."""
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    campaign_id = create_campaign(dsn, "Campaña con evidencia", {}, "user:campaign-manager")
    unit: dict[str, Any] = {
        "unit_id": uuid.uuid4().hex + uuid.uuid4().hex,
        "campaign_id": campaign_id,
        "challenge_id": "sec-tls",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": system_id,
        "node_key": "k-tls",
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None,
        "severity": "high",
    }
    verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": observed}]}})
    verdict_id, _ = persist_verdict(dsn, campaign_id, unit, verdict, probe_journal_seq=7)
    return campaign_id, verdict_id


def _index(dsn: str) -> list[tuple[str, str, str, str]]:
    with psycopg.connect(dsn) as conn:
        return [
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]))
            for r in conn.execute(
                "SELECT verdict_id, object_key, version_id, sha256 FROM argos.evidence_index"
            )
        ]


def test_a_verdict_becomes_an_immutable_indexed_artifact(migrated_db: str) -> None:
    store = _store()
    campaign_id, verdict_id = _verdict(migrated_db)
    record = write_artifact(migrated_db, store, campaign_id, verdict_id, _until())
    assert record.key == artifact_key(campaign_id, verdict_id)
    body = store.get(record.key, record.version_id)
    assert verify_artifact(body)
    assert record.sha256 == hashlib.sha256(body).hexdigest()
    assert _index(migrated_db) == [(verdict_id, record.key, record.version_id, record.sha256)]


def test_writing_again_is_idempotent_and_checks_the_bytes(migrated_db: str) -> None:
    store = _store()
    campaign_id, verdict_id = _verdict(migrated_db)
    first = write_artifact(migrated_db, store, campaign_id, verdict_id, _until())
    again = write_artifact(migrated_db, store, campaign_id, verdict_id, _until())
    assert again == first
    assert len(_index(migrated_db)) == 1


def test_a_lost_index_row_is_rebuilt_from_the_same_bytes(migrated_db: str) -> None:
    store = _store()
    campaign_id, verdict_id = _verdict(migrated_db)
    first = write_artifact(migrated_db, store, campaign_id, verdict_id, _until())
    with psycopg.connect(migrated_db) as conn:
        conn.execute("ALTER TABLE argos.evidence_index DISABLE TRIGGER evidence_index_write_once")
        conn.execute("DELETE FROM argos.evidence_index")
        conn.execute("ALTER TABLE argos.evidence_index ENABLE TRIGGER evidence_index_write_once")
    rebuilt = write_artifact(migrated_db, store, campaign_id, verdict_id, _until())
    assert rebuilt == first


def test_the_index_is_written_once(migrated_db: str) -> None:
    campaign_id, verdict_id = _verdict(migrated_db)
    write_artifact(migrated_db, _store(), campaign_id, verdict_id, _until())
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.evidence_index SET sha256 = repeat('0', 64)")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.evidence_index")


def test_a_verdict_of_another_campaign_is_refused(migrated_db: str) -> None:
    campaign_id, verdict_id = _verdict(migrated_db)
    other = create_campaign(migrated_db, "Otra campaña", {}, "user:campaign-manager")
    with pytest.raises(LookupError):
        write_artifact(migrated_db, _store(), other, verdict_id, _until())
    assert campaign_id != other
