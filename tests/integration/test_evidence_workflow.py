"""ARG-061…068 · a sealed campaign carried to its credential by one idempotent workflow."""

import asyncio
import datetime as dt
import os
import uuid
from collections import Counter
from typing import Any

import boto3
import httpx
import psycopg
import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from argos_challenges.evaluator import evaluate
from argos_challenges.seal import seal_campaign
from argos_challenges.store import create_campaign, persist_verdict
from argos_common.config import get_config
from argos_common.release import VaultTransitSigner
from argos_evidence.activities import EvidenceActivities
from argos_evidence.settings import EvidenceSettings
from argos_evidence.tsa import http_transport
from argos_evidence.workflow import EvidenceWorkflow
from argos_evidence.worm import EVIDENCE_BUCKET, WormStore, ensure_buckets
from argos_verifier.checks import Trust, verify_bundle

from .campaign_helpers import running

pytestmark = pytest.mark.integration

TSA = os.environ.get("ARGOS_TEST_TSA", "http://127.0.0.1:3180")
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7075",
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )


def _settings() -> EvidenceSettings:
    return EvidenceSettings(
        ISSUER_DID="did:web:evidence.argos.example",
        STATUS_BASE_URL="https://evidence.argos.example/status",
        CREDENTIAL_BASE_URL="https://evidence.argos.example/credentials",
        VERIFIER_URL="https://verify.argos.example/check",
        RETENTION_DAYS=1,
    )


class FlakyTransport:
    """The TSA is out of reach for the first ``failures`` attempts."""

    def __init__(self, failures: int) -> None:
        self._failures = failures
        self._real = http_transport(TSA)

    def __call__(self, query: bytes) -> bytes:
        if self._failures > 0:
            self._failures -= 1
            raise httpx.ConnectError("no window to the TSA")
        return self._real(query)


def _activities(dsn: str, failures: int = 0) -> EvidenceActivities:
    client = _client()
    ensure_buckets(client, default_retention_days=1)
    roots_pem = httpx.get(f"{TSA}/ca.pem").text
    return EvidenceActivities(
        dsn,
        WormStore(client),
        VaultTransitSigner(VAULT, "root", key="argos-evidence"),
        _settings(),
        FlakyTransport(failures),
        [roots_pem],
    )


def _sealed_campaign(dsn: str) -> str:
    campaign_id = create_campaign(dsn, "Campaña con cierre de evidencia", {}, "user:manager")
    for name, value in (("ok", "on"), ("ko", "off")):
        unit: dict[str, Any] = {
            "unit_id": uuid.uuid4().hex + uuid.uuid4().hex,
            "campaign_id": campaign_id,
            "challenge_id": f"sec-tls-{name}",
            "challenge_version": "1.0",
            "obligation": "OBL-RGPD-32-3",
            "system_id": str(uuid.uuid4()),
            "node_key": f"k-{name}",
            "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
            "sampling": None,
            "severity": "high",
        }
        verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": value}]}})
        persist_verdict(dsn, campaign_id, unit, verdict, probe_journal_seq=1)
    running(dsn, campaign_id)
    seal_campaign(dsn, campaign_id)
    return campaign_id


async def _run(activities: EvidenceActivities, campaign_id: str, attempts: int) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    queue = f"argos-evidence-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client,
        task_queue=queue,
        workflows=[EvidenceWorkflow],
        activities=activities.all(),
    ):
        result: dict[str, Any] = await client.execute_workflow(
            EvidenceWorkflow.run,
            args=[campaign_id, attempts, 1],
            id=f"evidence-test-{uuid.uuid4().hex[:8]}",
            task_queue=queue,
            execution_timeout=dt.timedelta(minutes=3),
        )
    return result


def _versions(campaign_id: str) -> Counter[str]:
    listed = _client().list_object_versions(
        Bucket=EVIDENCE_BUCKET, Prefix=f"campaigns/{campaign_id}/"
    )
    return Counter(v["Key"] for v in listed.get("Versions", []))


def test_the_chain_ends_in_a_verifiable_credential(migrated_db: str) -> None:
    campaign_id = _sealed_campaign(migrated_db)
    activities = _activities(migrated_db)
    result = asyncio.run(_run(activities, campaign_id, attempts=0))
    assert result["time_stamp"] == "stamped"
    assert result["artifacts"] == 2
    with psycopg.connect(migrated_db) as conn:
        credentials = conn.execute(
            "SELECT dossier_sha256 FROM argos.credentials WHERE campaign_id = %s", (campaign_id,)
        ).fetchall()
    assert [r[0] for r in credentials] == [result["dossier"]]
    report = verify_bundle(
        activities.bundle(result["dossier"]), Trust.from_mapping(activities.trust_anchors())
    )
    assert report.ok, [c for c in report.checks if c.status != "passed"]
    assert {c.status for c in report.checks} == {"passed"}


def test_a_failure_half_way_and_its_retry_leave_the_same_objects(migrated_db: str) -> None:
    campaign_id = _sealed_campaign(migrated_db)
    activities = _activities(migrated_db)
    activities.write_artifacts_now(campaign_id)
    activities.build_root_now(campaign_id)
    halfway = _versions(campaign_id)
    asyncio.run(_run(activities, campaign_id, attempts=0))
    asyncio.run(_run(activities, campaign_id, attempts=0))
    finished = _versions(campaign_id)
    assert set(halfway) <= set(finished)
    assert all(count == 1 for count in finished.values()), finished


def test_a_late_stamp_makes_a_new_dossier_and_supersedes_the_credential(
    migrated_db: str,
) -> None:
    campaign_id = _sealed_campaign(migrated_db)
    result = asyncio.run(_run(_activities(migrated_db, failures=1), campaign_id, attempts=3))
    assert result["time_stamp"] == "stamped"
    with psycopg.connect(migrated_db) as conn:
        dossiers = conn.execute(
            "SELECT sha256 FROM argos.dossiers WHERE campaign_id = %s ORDER BY created_at",
            (campaign_id,),
        ).fetchall()
        revoked = conn.execute(
            "SELECT c.dossier_sha256, r.reason FROM argos.credential_revocations r"
            " JOIN argos.credentials c ON c.id = r.credential_id WHERE c.campaign_id = %s",
            (campaign_id,),
        ).fetchall()
    assert len(dossiers) == 2
    assert result["dossier"] == dossiers[-1][0]
    assert [r[0] for r in revoked] == [dossiers[0][0]]
    assert "superseded" in revoked[0][1]


def test_a_stamp_that_never_comes_leaves_an_honest_dossier(migrated_db: str) -> None:
    campaign_id = _sealed_campaign(migrated_db)
    result = asyncio.run(_run(_activities(migrated_db, failures=100), campaign_id, attempts=1))
    assert result["time_stamp"] == "queued"
    with psycopg.connect(migrated_db) as conn:
        count = conn.execute(
            "SELECT count(*) FROM argos.credentials WHERE campaign_id = %s", (campaign_id,)
        ).fetchone()
    assert count == (1,)
