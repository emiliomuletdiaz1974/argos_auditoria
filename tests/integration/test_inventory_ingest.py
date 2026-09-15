"""ARG-022 · ingest: idempotent materialisation of DISCOVERY events in the inventory graph."""

import asyncio
from typing import Any

import pytest
from fixtures.ground_truth import load_ground_truth

from argos_common.secret_stores import VaultSecretStore
from argos_inventory.discovery.scanner import scan_system
from argos_inventory.graph.model import table_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .sources import VAULT, catalog_system, connector_token, register_catalog_system

pytestmark = pytest.mark.integration

AT1 = "2026-09-15T10:00:00+00:00"
AT2 = "2026-09-16T10:00:00+00:00"


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        self.events.append((subject, event_type, data))
        return len(self.events)


def _provenance(system_id: str, at: str, run: str = "run-1") -> dict[str, Any]:
    return {
        "system_id": system_id,
        "run_id": run,
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": f"probe-{run}",
        "journal_seq": 7,
        "observed_at": at,
    }


def _table(system_id: str, at: str, est_rows: int, columns: list[str]) -> dict[str, Any]:
    return {
        **_provenance(system_id, at),
        "schema": "clinic",
        "table": "patients",
        "est_rows": est_rows,
        "bytes": 8192,
        "comment": None,
        "columns": [{"name": c, "type": "TEXT", "nullable": True} for c in columns],
    }


def _event(event_type: str) -> dict[str, Any]:
    return {"type": f"eu.argos.{event_type}"}


def _count(store: GraphStore, cypher: str) -> int:
    return int(store.query(cypher, columns=("n",))[0]["n"])


def _ingest(ingestor: Ingestor, event_type: str, data: dict[str, Any]) -> None:
    asyncio.run(ingestor.handle(data, _event(event_type)))


def test_table_found_materialises_the_asset_hierarchy(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    table = _table(system_id, AT1, 5000, ["id", "national_id"])
    _ingest(ingestor, "discovery.table_found.v1", table)
    rows = store.query(
        "MATCH (s:System {id: $sid})-[:CONTAINS]->(h:Schema)-[:CONTAINS]->(t:Table)"
        "-[:CONTAINS]->(c:Column) RETURN s.name, s.kind, h.name, t.qualified_name, t.est_rows, "
        "t.first_seen, t.probe_id, c.qualified_name ORDER BY c.qualified_name",
        {"sid": system_id},
        ("system", "kind", "schema", "table", "est_rows", "first_seen", "probe_id", "column"),
    )
    assert [r["column"] for r in rows] == ["clinic.patients.id", "clinic.patients.national_id"]
    assert rows[0] | {"column": None} == {
        "system": "dev-source-postgres",
        "kind": "rdbms",
        "schema": "clinic",
        "table": "clinic.patients",
        "est_rows": 5000,
        "first_seen": AT1,
        "probe_id": "probe-run-1",
        "column": None,
    }


def test_replaying_the_same_events_changes_nothing(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    table = _table(system_id, AT1, 5000, ["id", "national_id", "birth_date"])
    for _ in range(3):
        _ingest(ingestor, "discovery.table_found.v1", table)
    assert _count(store, "MATCH (n) RETURN count(n)") == 1 + 1 + 1 + 3 + 9  # + 9 root categories
    assert _count(store, "MATCH ()-[e:CONTAINS]->() RETURN count(e)") == 5


def test_a_new_observation_moves_last_seen_and_keeps_the_growth_baseline(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    _ingest(ingestor, "discovery.table_found.v1", _table(system_id, AT1, 20000, ["id"]))
    store.execute(
        "MATCH (t:Table {key: $key}) SET t.missing = true SET t.missing_since = $at",
        {"key": table_key(system_id, "clinic", "patients"), "at": AT1},
    )
    _ingest(ingestor, "discovery.table_found.v1", _table(system_id, AT2, 70000, ["id"]))
    [row] = store.query(
        "MATCH (t:Table {key: $key}) RETURN t.first_seen, t.last_seen, t.est_rows_prev, "
        "t.est_rows, t.missing, t.missing_since",
        {"key": table_key(system_id, "clinic", "patients")},
        ("first_seen", "last_seen", "prev", "rows", "missing", "since"),
    )
    assert row == {
        "first_seen": AT1,
        "last_seen": AT2,
        "prev": 20000,
        "rows": 70000,
        "missing": False,
        "since": None,
    }


def test_access_found_links_database_roles_with_their_privileges(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    _ingest(ingestor, "discovery.table_found.v1", _table(system_id, AT1, 5000, ["id"]))
    grants = [
        {"grantee": "clinic_admin", "privilege": "DELETE"},
        {"grantee": "clinic_admin", "privilege": "SELECT"},
        {"grantee": "argos_ro", "privilege": "SELECT (effective)"},
    ]
    access = {
        **_provenance(system_id, AT1),
        "schema": "clinic",
        "table": "patients",
        "grants": grants,
    }
    _ingest(ingestor, "discovery.access_found.v1", access)
    _ingest(ingestor, "discovery.access_found.v1", access)
    rows = store.query(
        "MATCH (i:Identity)-[a:CAN_ACCESS]->(t:Table) RETURN i.name, i.kind, a.privileges "
        "ORDER BY i.name",
        columns=("name", "kind", "privileges"),
    )
    assert rows == [
        {"name": "argos_ro", "kind": "database_role", "privileges": ["SELECT (effective)"]},
        {"name": "clinic_admin", "kind": "database_role", "privileges": ["DELETE", "SELECT"]},
    ]
    assert _count(store, "MATCH (:System)-[:CONTAINS]->(i:Identity) RETURN count(i)") == 0


def test_summaries_land_on_the_system_and_file_areas(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    files_id = register_catalog_system(migrated_db, "dev-files-local")
    api_id = register_catalog_system(migrated_db, "dev-api-keycloak")
    area = {
        **_provenance(files_id, AT1),
        "path": "",
        "total": 121,
        "bytes": 9000,
        "by_ext": {"onnx": 1, "pdf": 20},
        "age_years": {"0": 121},
        "capped": False,
    }
    routes = {
        **_provenance(api_id, AT1),
        "routes": [{"path": "/realms/{realm}", "status": 405, "content_type": None}],
    }
    _ingest(ingestor, "discovery.file_area_scanned.v1", area)
    _ingest(ingestor, "discovery.api_routes_found.v1", routes)
    [file_row] = store.query(
        "MATCH (:System {id: $sid})-[:CONTAINS]->(f:FileArea) RETURN f.name, f.total, f.by_ext",
        {"sid": files_id},
        ("name", "total", "by_ext"),
    )
    assert file_row == {"name": "/", "total": 121, "by_ext": {"onnx": 1, "pdf": 20}}
    [api_row] = store.query(
        "MATCH (s:System {id: $sid}) RETURN s.kind, s.routes, s.summary_kind",
        {"sid": api_id},
        ("kind", "routes", "summary_kind"),
    )
    assert api_row == {
        "kind": "api",
        "routes": ["/realms/{realm}"],
        "summary_kind": "api_routes_found",
    }


def test_scan_completed_publishes_ingested(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-api-keycloak")
    store = GraphStore(migrated_db)
    bus = RecordingBus()
    ingestor = Ingestor(store, migrated_db, bus)
    completed = {
        "system_id": system_id,
        "run_id": "run-9",
        "status": "completed",
        "started_at": AT1,
        "finished_at": AT2,
        "events": 1,
        "failed_probes": 0,
        "error": None,
    }
    _ingest(ingestor, "discovery.scan_completed.v1", completed)
    assert bus.events == [
        (
            "argos.discovery.ingested",
            "discovery.ingested.v1",
            {"system_id": system_id, "run_id": "run-9", "status": "completed"},
        )
    ]
    [row] = store.query(
        "MATCH (s:System {id: $sid}) RETURN s.last_scan_run, s.last_scan_status, s.last_scan_at",
        {"sid": system_id},
        ("run", "status", "at"),
    )
    assert row == {"run": "run-9", "status": "completed", "at": AT2}


def test_events_the_ingest_does_not_handle_are_ignored(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    bus = RecordingBus()
    ingestor = Ingestor(store, migrated_db, bus)
    asyncio.run(ingestor.handle({"system_id": "x"}, _event("discovery.delta_ready.v1")))
    asyncio.run(ingestor.handle({}, {}))
    assert bus.events == [] and _count(store, "MATCH (n:System) RETURN count(n)") == 0


def test_a_real_postgres_scan_lands_the_ground_truth_tables(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    scan_bus = RecordingBus()
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())

    async def scan_then_ingest() -> None:
        store_secrets = VaultSecretStore(VAULT, connector_token())
        await scan_system(migrated_db, store_secrets, scan_bus, system_id)
        for _, event_type, data in scan_bus.events:
            await ingestor.handle(data, {"type": f"eu.argos.{event_type}"})

    asyncio.run(scan_then_ingest())
    rows = store.query(
        "MATCH (:System {id: $sid})-[:CONTAINS*2]->(t:Table)-[:CONTAINS]->(c:Column) "
        "RETURN t.qualified_name, c.name",
        {"sid": system_id},
        ("table", "column"),
    )
    live: dict[str, set[str]] = {}
    for row in rows:
        live.setdefault(row["table"], set()).add(row["column"])
    expected = load_ground_truth().tables("dev-source-postgres")
    assert live == {table: set(columns) for table, columns in expected.items()}
    assert catalog_system("dev-source-postgres")["id"] == system_id
