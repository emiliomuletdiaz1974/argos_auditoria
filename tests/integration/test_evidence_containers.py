"""ARG-061…068 · the evidence containers: a sealed campaign announced on NATS ends in a credential.

Runs against the development environment (`make dev`), not a test database:
the containers use the development one. The campaign is created with random
ids and needs no source system.
"""

import asyncio
import os
import time
import uuid
from typing import Any

import httpx
import psycopg
import pytest

from argos_challenges.evaluator import evaluate
from argos_challenges.seal import announce_seal, seal_campaign
from argos_challenges.store import create_campaign, persist_verdict
from argos_common.release import VaultTransitSigner
from argos_events import Bus
from argos_evidence.credential.multibase import public_key_from_multibase
from argos_evidence.credential.verify import verify_credential

from .campaign_helpers import running
from .conftest import ADMIN_DSN

pytestmark = pytest.mark.integration

API = "http://127.0.0.1:8008"
NATS = os.environ.get("ARGOS_TEST_NATS", "nats://argos-dev:dev-only-nats-host@127.0.0.1:4222")
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def _sealed_in_development() -> dict[str, Any]:
    campaign_id = create_campaign(ADMIN_DSN, "Campaña del contenedor de evidencia", {}, "user:m")
    unit: dict[str, Any] = {
        "unit_id": uuid.uuid4().hex + uuid.uuid4().hex,
        "campaign_id": campaign_id,
        "challenge_id": "sec-tls-container",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": str(uuid.uuid4()),
        "node_key": "k-container",
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None,
        "severity": "high",
    }
    verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": "on"}]}})
    persist_verdict(ADMIN_DSN, campaign_id, unit, verdict, probe_journal_seq=1)
    running(ADMIN_DSN, campaign_id)
    return seal_campaign(ADMIN_DSN, campaign_id)


async def _announce(sealed: dict[str, Any]) -> None:
    bus = Bus("argos-test", NATS)
    await bus.connect()
    try:
        await announce_seal(bus, sealed)
    finally:
        await bus.close()


def _credential_of(campaign_id: str, timeout: float = 120) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with psycopg.connect(ADMIN_DSN) as conn:
            row = conn.execute(
                "SELECT id FROM argos.credentials WHERE campaign_id = %s ORDER BY issued_at DESC",
                (campaign_id,),
            ).fetchone()
        if row is not None:
            return str(row[0])
        time.sleep(2)
    raise AssertionError(f"no credential for {campaign_id} after {timeout} s")


def test_the_api_publishes_the_did_of_the_signing_key() -> None:
    assert httpx.get(f"{API}/health", timeout=5).json() == {"status": "ok"}
    did = httpx.get(f"{API}/.well-known/did.json", timeout=5).json()
    key = VaultTransitSigner(VAULT, "root", key="argos-evidence").public_key()
    method = did["verificationMethod"][0]
    assert public_key_from_multibase(method["publicKeyMultibase"]) == key
    assert httpx.get(f"{API}/docs", timeout=5).status_code == 404


def test_a_sealed_campaign_announced_on_nats_ends_in_a_verifiable_credential() -> None:
    sealed = _sealed_in_development()
    asyncio.run(_announce(sealed))
    asyncio.run(_announce(sealed))  # a repeated announcement starts nothing twice
    credential_id = _credential_of(str(sealed["campaign_id"]))
    credential = httpx.get(
        f"{API}/credentials/{credential_id.removeprefix('urn:uuid:')}", timeout=10
    )
    assert credential.headers["content-type"].startswith("application/vc+json")
    document = credential.json()
    status_url = document["credentialStatus"]["statusListCredential"]
    number = status_url.rsplit("/", 1)[1]
    status = httpx.get(f"{API}/status/{number}", timeout=10).json()
    did = httpx.get(f"{API}/.well-known/did.json", timeout=5).json()
    check = verify_credential(document, did, status)
    assert check.valid, check.reasons
    with psycopg.connect(ADMIN_DSN) as conn:
        runs = conn.execute(
            "SELECT count(*) FROM argos.campaign_signatures WHERE campaign_id = %s",
            (str(sealed["campaign_id"]),),
        ).fetchone()
    assert runs == (1,)


def test_the_api_serves_no_dossier_and_no_unknown_credential() -> None:
    assert httpx.get(f"{API}/credentials/../dossiers", timeout=5).status_code == 404
    assert httpx.get(f"{API}/credentials/{uuid.uuid4()}", timeout=5).status_code == 404


def test_an_announcement_of_a_campaign_it_does_not_hold_starts_nothing() -> None:
    stranger = str(uuid.uuid4())
    asyncio.run(_announce({"campaign_id": stranger, "seal": "0" * 64, "verdicts": 0}))
    time.sleep(3)
    assert asyncio.run(_evidence_workflow_exists(stranger)) is False


async def _evidence_workflow_exists(campaign_id: str) -> bool:
    from temporalio.client import Client
    from temporalio.service import RPCError

    client = await Client.connect(os.environ.get("ARGOS_TEST_TEMPORAL", "127.0.0.1:7233"))
    try:
        await client.get_workflow_handle(f"evidence-{campaign_id}").describe()
    except RPCError:
        return False
    return True
