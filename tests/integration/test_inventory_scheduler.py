"""ARG-030 · rescan scoring over the catalog, the ingestion wait and the Temporal pipeline."""

import asyncio
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.types.json import Jsonb
from temporalio.client import Client, ScheduleOverlapPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from argos_connector.budget import DAYS
from argos_inventory.graph.store import GraphStore
from argos_inventory.scheduler.activities import INGESTION_PENDING, InventoryActivities
from argos_inventory.scheduler.policy import select_launches
from argos_inventory.scheduler.worker import SCHEDULE_ID, create_worker, ensure_schedule
from argos_inventory.scheduler.workflows import RescanPlanner

from .inventory_helpers import IngestingBus, RecordingBus, scan_and_ingest, secret_store
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

TEMPORAL = "127.0.0.1:7233"
FAST_BUDGET = {"queries_per_minute": 600, "burst": 100}


def _set_budget(dsn: str, system_id: str, budget: dict[str, Any]) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.systems SET connection = jsonb_set(connection, '{config,budget}', %s) "
            "WHERE id = %s",
            (Jsonb(budget), system_id),
        )


async def test_score_systems_prefers_never_scanned_systems(migrated_db: str) -> None:
    scanned = await asyncio.to_thread(scan_and_ingest, migrated_db, "dev-source-postgres")
    fresh = register_catalog_system(migrated_db, "dev-source-mariadb")
    activities = InventoryActivities(migrated_db, secret_store(), RecordingBus())
    ranked = await ActivityEnvironment().run(activities.score_systems)
    by_id = {s.system_id: s for s in ranked}
    assert ranked[0].system_id == fresh
    assert by_id[fresh].score == 1998.0
    assert by_id[scanned].score < 1.0
    assert all(s.in_window for s in ranked)


async def test_systems_outside_their_window_are_not_eligible(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-mariadb")
    today = datetime.now(ZoneInfo("Europe/Madrid")).weekday()
    other_day = next(name for name, number in DAYS.items() if number == (today + 3) % 7)
    _set_budget(
        migrated_db,
        system_id,
        {"windows": [{"days": other_day, "from": "00:00", "to": "23:59"}]},
    )
    activities = InventoryActivities(migrated_db, secret_store(), RecordingBus())
    [scored] = await ActivityEnvironment().run(activities.score_systems)
    assert scored.in_window is False
    assert select_launches([scored]) == []


async def test_deltas_wait_until_the_run_is_ingested(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-api-keycloak")
    activities = InventoryActivities(migrated_db, secret_store(), RecordingBus())
    with pytest.raises(ApplicationError) as caught:
        await ActivityEnvironment().run(activities.compute_run_deltas, system_id, str(uuid.uuid4()))
    assert caught.value.type == INGESTION_PENDING
    assert caught.value.non_retryable is False


async def test_rescan_planner_runs_the_whole_pipeline(migrated_db: str) -> None:
    postgres = register_catalog_system(migrated_db, "dev-source-postgres")
    mariadb = register_catalog_system(migrated_db, "dev-source-mariadb")
    for system_id in (postgres, mariadb):
        _set_budget(migrated_db, system_id, FAST_BUDGET)
    bus = IngestingBus(migrated_db)
    activities = InventoryActivities(migrated_db, secret_store(), bus)
    client = await Client.connect(TEMPORAL, namespace="default")
    task_queue = f"argos-inventory-test-{uuid.uuid4().hex[:8]}"

    async with create_worker(client, activities, task_queue):
        first = await client.execute_workflow(
            RescanPlanner.run, 2, id=f"planner-{uuid.uuid4()}", task_queue=task_queue
        )
        second = await client.execute_workflow(
            RescanPlanner.run, 2, id=f"planner-{uuid.uuid4()}", task_queue=task_queue
        )

    assert first["launched"] == 2
    assert {s["system_id"] for s in first["scans"]} == {postgres, mariadb}
    assert all(s["status"] == "completed" for s in first["scans"])
    baseline = {"appeared": 0, "disappeared": 0, "anomalous_growth": 0}
    assert all(s["deltas"] == baseline for s in first["scans"])
    assert first["refresh"]["ai_signals"] >= 1
    assert second == {"launched": 0, "scans": [], "refresh": None}

    with psycopg.connect(migrated_db) as conn:
        runs = conn.execute("SELECT system_id::text, status FROM argos.scan_runs").fetchall()
    assert sorted(runs) == sorted([(postgres, "completed"), (mariadb, "completed")])
    store = GraphStore(migrated_db)
    [classified] = store.query(
        "MATCH (c:Column)-[:CLASSIFIED_AS]->(:Category) RETURN count(c)", columns=("n",)
    )
    assert classified["n"] > 0
    flows = store.query(
        "MATCH (:System {id: $a})-[f:FLOWS_TO]->(:System {id: $b}) RETURN f.method",
        {"a": postgres, "b": mariadb},
        ("method",),
    )
    assert {"method": "engine_catalog"} in flows


async def test_the_hourly_schedule_is_created_once() -> None:
    client = await Client.connect(TEMPORAL, namespace="default")
    schedule_id = f"{SCHEDULE_ID}-test-{uuid.uuid4().hex[:8]}"
    try:
        created = await ensure_schedule(client, "argos-inventory-test", schedule_id, paused=True)
        assert created is True
        again = await ensure_schedule(client, "argos-inventory-test", schedule_id, paused=True)
        assert again is False
        described = await client.get_schedule_handle(schedule_id).describe()
        assert described.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert described.schedule.state.paused is True
    finally:
        await client.get_schedule_handle(schedule_id).delete()
