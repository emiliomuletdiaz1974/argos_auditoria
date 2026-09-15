"""ARG-022 · the discovery scanner runs read-only probes and records every run (F03-02)."""

import asyncio
import json
import uuid
from typing import Any

import psycopg
import pytest

from argos_common.secret_stores import VaultSecretStore
from argos_events import Bus
from argos_inventory.discovery.scanner import scan_system

from .sources import VAULT, catalog_system, connector_token

pytestmark = pytest.mark.integration

NATS = "nats://127.0.0.1:4222"
POSTGRES_TABLES = {"appointments", "consents", "patient_documents", "patients", "readmission_risk"}


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        self.events.append((subject, event_type, data))
        return len(self.events)


def _register(dsn: str, name: str, connector: str | None = None) -> str:
    system = catalog_system(name)
    connection = {
        "secret": f"connectors/{system['id']}",
        "connector": connector or system["connector"],
        "config": system.get("config", {}),
    }
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, connection) VALUES (%s, %s, %s, %s::jsonb)",
            (system["id"], system["name"], system["kind"], json.dumps(connection)),
        )
    return str(system["id"])


def _store() -> VaultSecretStore:
    return VaultSecretStore(VAULT, connector_token())


def test_scans_postgres_tables_and_grants(migrated_db: str) -> None:
    system_id = _register(migrated_db, "dev-source-postgres")
    bus = RecordingBus()
    summary = asyncio.run(scan_system(migrated_db, _store(), bus, system_id))
    assert summary.status == "completed" and summary.failed_probes == 0, summary

    tables = {d["table"]: d for _, t, d in bus.events if t == "discovery.table_found.v1"}
    assert set(tables) >= POSTGRES_TABLES
    patients = tables["patients"]
    assert [c["name"] for c in patients["columns"]] == [
        "id",
        "national_id",
        "full_name",
        "birth_date",
        "created_at",
    ]
    assert patients["est_rows"] > 0 and patients["journal_seq"] > 0
    grants = {
        f"{g['grantee']}:{g['privilege']}"
        for _, t, d in bus.events
        if t == "discovery.access_found.v1" and d["table"] == "patients"
        for g in d["grants"]
    }
    assert {"clinic_admin:DELETE", "argos_ro:SELECT (effective)"} <= grants
    assert bus.events[-1][1] == "discovery.scan_completed.v1"
    assert bus.events[-1][2]["events"] == summary.events == len(bus.events) - 1

    with psycopg.connect(migrated_db) as conn:
        run = conn.execute(
            "SELECT status, events, finished_at IS NOT NULL, prev_run FROM argos.scan_runs "
            "WHERE id = %s",
            (summary.run_id,),
        ).fetchone()
        emitted = conn.execute(
            "SELECT count(*) FROM argos.connector_queries "
            "WHERE system_id = %s AND status = 'emitted'",
            (system_id,),
        ).fetchone()
    assert run == ("completed", summary.events, True, None)
    assert emitted == (0,)


@pytest.mark.parametrize(
    ("name", "event_type"),
    [
        ("dev-files-local", "discovery.file_area_scanned.v1"),
        ("dev-directory-ldap", "discovery.directory_summarized.v1"),
        ("dev-api-keycloak", "discovery.api_routes_found.v1"),
        ("dev-clinical-fhir", "discovery.clinical_resources_found.v1"),
        ("dev-clinical-dicom", "discovery.clinical_resources_found.v1"),
    ],
)
def test_scans_every_other_source_kind(migrated_db: str, name: str, event_type: str) -> None:
    system_id = _register(migrated_db, name)
    bus = RecordingBus()
    summary = asyncio.run(scan_system(migrated_db, _store(), bus, system_id))
    assert summary.status == "completed", summary
    assert [t for _, t, _ in bus.events] == [event_type, "discovery.scan_completed.v1"]


def test_second_run_links_the_previous_completed_run(migrated_db: str) -> None:
    system_id = _register(migrated_db, "dev-api-keycloak")
    store = _store()
    first = asyncio.run(scan_system(migrated_db, store, RecordingBus(), system_id))
    second = asyncio.run(scan_system(migrated_db, store, RecordingBus(), system_id))
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT prev_run FROM argos.scan_runs WHERE id = %s", (second.run_id,)
        ).fetchone()
    assert row == (uuid.UUID(first.run_id),)


def test_a_failing_discovery_marks_the_run_failed_without_raising(migrated_db: str) -> None:
    system_id = _register(migrated_db, "dev-api-keycloak", connector="os:system")
    bus = RecordingBus()
    summary = asyncio.run(scan_system(migrated_db, _store(), bus, system_id))
    assert (summary.status, summary.error, summary.events) == ("failed", "ValueError", 0)
    [(_subject, event_type, data)] = bus.events
    assert event_type == "discovery.scan_completed.v1" and data["status"] == "failed"
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT status, error FROM argos.scan_runs WHERE id = %s", (summary.run_id,)
        ).fetchone()
    assert row == ("failed", "ValueError")


def test_scan_completed_reaches_the_discovery_stream(migrated_db: str) -> None:
    system_id = _register(migrated_db, "dev-api-keycloak")

    async def scan_and_listen() -> dict[str, Any]:
        bus = Bus("inventory-scanner-test", NATS)
        await bus.connect()
        received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def handler(data: dict[str, Any], event: dict[str, Any]) -> None:
            await received.put(data)

        durable = f"scan-test-{uuid.uuid4().hex[:12]}"
        try:
            summary = await scan_system(migrated_db, _store(), bus, system_id)
            await bus.subscribe("argos.discovery.scan_completed", durable=durable, handler=handler)
            while True:
                data = await asyncio.wait_for(received.get(), timeout=15)
                if data["run_id"] == summary.run_id:
                    return data
        finally:
            await bus.js.delete_consumer("DISCOVERY", durable)
            await bus.close()

    data = asyncio.run(scan_and_listen())
    assert data["status"] == "completed" and data["system_id"] == system_id
