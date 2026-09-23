"""ARG-043 · a campaign from end to end against Temporal: gates, pause, verdicts and seal."""

import asyncio
import os
import uuid
from typing import Any

import psycopg
import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from argos_challenges.activities import ChallengeActivities
from argos_challenges.seal import verify_seal
from argos_challenges.store import campaign_record, create_campaign, grant_approval
from argos_challenges.workflows import CampaignWorkflow, SystemRun
from argos_common.config import get_config
from argos_common.release import VaultTransitSigner
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_ontology.bundle import publish_library
from argos_ontology.vocabulary import LIBRARY_DIR

from .inventory_helpers import probe_runner, scan_and_ingest, secret_store

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SECOND_DPO = "user:second-dpo"
SYSTEMS = ("dev-source-postgres", "dev-source-mariadb")
ONTOLOGY_VERSION = "1.0.0"


@pytest.fixture
def prepared(migrated_db: str) -> str:
    """A graph with both sources, an ontology version in force and a planned campaign."""
    store = GraphStore(migrated_db)
    for name in SYSTEMS:
        system_id = scan_and_ingest(migrated_db, name)
        classify_new_columns(store, probe_runner(migrated_db), system_id)
    discover_ai(store)
    # The campaign runs from signed content only (SEC-011): the library is published as a bundle.
    publish_library(
        migrated_db,
        LIBRARY_DIR,
        ONTOLOGY_VERSION,
        __import__("datetime").date(2024, 8, 1),
        VaultTransitSigner(
            os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200"), "root", key="argos-content"
        ),
    )
    return create_campaign(migrated_db, "Campaña de integración", {}, MANAGER)


async def _run_campaign(
    dsn: str, campaign_id: str, approve_sampling: bool = True
) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(dsn, secret_store())
    queue = f"argos-campaigns-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client,
        task_queue=queue,
        workflows=[CampaignWorkflow, SystemRun],
        activities=[
            activities.prepare_campaign,
            activities.request_approval,
            activities.check_gate,
            activities.set_campaign_status,
            activities.probe,
            activities.wait_window,
            activities.evaluate_unit,
            activities.seal,
            activities.check_reversions,
        ],
    ):
        handle = await client.start_workflow(
            CampaignWorkflow.run,
            campaign_id,
            id=f"campaign-{campaign_id}",
            task_queue=queue,
        )
        await _wait_for_gate(handle, "awaiting:start")
        grant_approval(dsn, campaign_id, "start", DPO)
        await handle.signal(CampaignWorkflow.approve, "start")
        if approve_sampling and await _next_status(handle, "awaiting:start") == "awaiting:sampling":
            grant_approval(dsn, campaign_id, "sampling", DPO, needed=2)
            grant_approval(dsn, campaign_id, "sampling", SECOND_DPO, needed=2)
            await handle.signal(CampaignWorkflow.approve, "sampling")
        return dict(await handle.result())


async def _next_status(handle: Any, current: str, tries: int = 60) -> str:
    for _ in range(tries):
        status = str((await handle.query(CampaignWorkflow.progress)).get("status"))
        if status != current:
            return status
        await asyncio.sleep(1)
    raise AssertionError(f"the campaign never left {current}")


async def _wait_for_gate(handle: Any, state: str, tries: int = 60) -> None:
    import asyncio

    for _ in range(tries):
        progress = await handle.query(CampaignWorkflow.progress)
        if progress.get("status") == state:
            return
        await asyncio.sleep(1)
    raise AssertionError(f"the campaign never reached {state}")


@pytest.mark.asyncio
async def test_a_campaign_waits_for_its_gate_runs_and_seals(
    migrated_db: str, prepared: str
) -> None:
    result = await _run_campaign(migrated_db, prepared)
    assert result["status"] == "sealed"
    assert result["done"] == result["total"] > 0
    record = campaign_record(migrated_db, prepared)
    assert record["status"] == "sealed" and record["seal"] == result["seal"]
    assert record["snapshot_id"] and record["ontology_version"] == ONTOLOGY_VERSION
    assert verify_seal(migrated_db, prepared)


@pytest.mark.asyncio
async def test_the_seal_is_verified_without_reading_the_whole_journal(
    migrated_db: str, prepared: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every GET of a campaign verifies its seal: walking the journal would grow with it forever.
    await _run_campaign(migrated_db, prepared)

    def whole_journal(*_: Any, **__: Any) -> Any:
        raise AssertionError("the seal check read the whole journal")

    monkeypatch.setattr("argos_common.journal_pg.PostgresJournal.read", whole_journal)
    assert verify_seal(migrated_db, prepared)


@pytest.mark.asyncio
async def test_touching_a_verdict_breaks_the_seal(migrated_db: str, prepared: str) -> None:
    await _run_campaign(migrated_db, prepared)
    assert verify_seal(migrated_db, prepared)
    with psycopg.connect(migrated_db) as conn:
        conn.execute("ALTER TABLE argos.verdicts DISABLE TRIGGER verdicts_write_once")
        conn.execute(
            "UPDATE argos.verdicts SET verdict_hash = %s "
            "WHERE campaign_id = %s AND verdict_hash = ("
            "  SELECT min(verdict_hash) FROM argos.verdicts WHERE campaign_id = %s)",
            ("0" * 64, prepared, prepared),
        )
        conn.execute("ALTER TABLE argos.verdicts ENABLE TRIGGER verdicts_write_once")
    assert not verify_seal(migrated_db, prepared)


@pytest.mark.asyncio
async def test_a_bare_signal_does_not_open_a_gate(migrated_db: str, prepared: str) -> None:
    # Whoever reaches Temporal can send the signal; only the approvals recorded by people open it.
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(migrated_db, secret_store())
    queue = f"argos-campaigns-test-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client,
        task_queue=queue,
        workflows=[CampaignWorkflow, SystemRun],
        activities=[
            activities.prepare_campaign,
            activities.request_approval,
            activities.check_gate,
            activities.set_campaign_status,
            activities.probe,
            activities.wait_window,
            activities.evaluate_unit,
            activities.seal,
            activities.check_reversions,
        ],
    ):
        handle = await client.start_workflow(
            CampaignWorkflow.run, prepared, id=f"campaign-{prepared}", task_queue=queue
        )
        await _wait_for_gate(handle, "awaiting:start")
        await handle.signal(CampaignWorkflow.approve, "start")
        await asyncio.sleep(5)
        progress = await handle.query(CampaignWorkflow.progress)
        assert progress["status"] == "awaiting:start"
        assert campaign_record(migrated_db, prepared)["status"] != "running"
        await handle.cancel()
