"""ARG-026 · catalog projection, coverage, freshness and the record of processing activities."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from argos_inventory.catalog.treatments import import_treatments
from argos_inventory.catalog.views import catalog_columns, coverage, freshness, refresh_catalog
from argos_inventory.graph.model import column_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-15T10:00:00+00:00"
DPO = "user:0192b000-0000-7000-8000-00000000d0c0"
CSV = (
    b"id;name;legal_basis;retention;systems\n"
    b"T-001;Synthetic clinical record;GDPR 9.2.h;15 years;dev-source-postgres\n"
    b"T-002;Synthetic billing;GDPR 6.1.b;6 years;\n"
)
CLASSIFY = (
    "MATCH (c:Column {key: $key}), (k:Category {name: $category}) "
    "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = $method SET r.confidence = $confidence"
)
COVERAGE_FIELDS = (
    "columns_total",
    "columns_classified",
    "coverage_pct",
    "special_columns",
    "dict_columns",
    "validator_columns",
    "ai_columns",
    "human_columns",
)


def _table(system_id: str, table: str, columns: list[str]) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "run_id": "run-1",
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": "p",
        "journal_seq": 1,
        "observed_at": AT,
        "schema": "clinic",
        "table": table,
        "est_rows": 10,
        "bytes": 8192,
        "comment": None,
        "columns": [{"name": c, "type": "text", "nullable": True} for c in columns],
    }


def _classify(store: GraphStore, key: str, category: str, method: str, confidence: float) -> None:
    params = {"key": key, "category": category, "method": method, "confidence": confidence}
    store.execute(CLASSIFY, params)


def _setup(dsn: str) -> tuple[str, str, GraphStore]:
    postgres = register_catalog_system(dsn, "dev-source-postgres")
    files = register_catalog_system(dsn, "dev-files-local")
    store = GraphStore(dsn)
    ingestor = Ingestor(store, dsn, RecordingBus())

    async def ingest() -> None:
        for data in (
            _table(postgres, "patients", ["national_id", "full_name", "department"]),
            _table(postgres, "notes", ["obs", "status"]),
        ):
            await ingestor.handle(data, {"type": "eu.argos.discovery.table_found.v1"})

    asyncio.run(ingest())

    def key(table: str, column: str) -> str:
        return column_key(postgres, "clinic", table, column)

    _classify(store, key("patients", "national_id"), "official_identifier", "validator:dni", 1.0)
    _classify(store, key("patients", "full_name"), "personal_data", "dict", 0.6)
    _classify(store, key("notes", "obs"), "special_category.health", "ai", 0.9)
    store.execute(
        "MATCH (c:Column {key: $key}) SET c.missing = true",
        {"key": key("patients", "department")},
    )
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.systems SET owner = 'dpo.synthetic@example.invalid' WHERE id = %s",
            (postgres,),
        )
        finished = datetime.now(UTC) - timedelta(hours=2)
        conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at, finished_at) "
            "VALUES (%s, %s, 'completed', %s, %s)",
            (str(uuid.uuid4()), postgres, finished - timedelta(minutes=5), finished),
        )
    return postgres, files, store


def test_catalog_columns_project_the_graph(migrated_db: str) -> None:
    postgres, _, _ = _setup(migrated_db)
    refresh_catalog(migrated_db)
    rows = {r["qualified_name"]: r for r in catalog_columns(migrated_db, postgres)}
    assert set(rows) == {
        "clinic.patients.national_id",
        "clinic.patients.full_name",
        "clinic.patients.department",
        "clinic.notes.obs",
        "clinic.notes.status",
    }
    national = rows["clinic.patients.national_id"]
    found = (national["system_name"], national["category"], national["method"])
    assert found == ("dev-source-postgres", "official_identifier", "validator:dni")
    assert national["confidence"] == 1.0
    status = rows["clinic.notes.status"]
    assert (status["category"], status["method"]) == ("unclassified", None)
    assert rows["clinic.patients.department"]["missing"] is True


def test_coverage_ignores_missing_columns(migrated_db: str) -> None:
    postgres, _, _ = _setup(migrated_db)
    refresh_catalog(migrated_db)
    [row] = [r for r in coverage(migrated_db) if r["system_id"] == postgres]
    assert {k: row[k] for k in COVERAGE_FIELDS} == {
        "columns_total": 4,
        "columns_classified": 3,
        "coverage_pct": 75.0,
        "special_columns": 1,
        "dict_columns": 1,
        "validator_columns": 1,
        "ai_columns": 1,
        "human_columns": 0,
    }


def test_refresh_is_repeatable_and_concurrent(migrated_db: str) -> None:
    _setup(migrated_db)
    refresh_catalog(migrated_db)
    refresh_catalog(migrated_db)
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'argos' AND tablename IN "
            "('catalog_columns', 'catalog_coverage')"
        ).fetchall()
    indexes = {r[0] for r in rows}
    assert {"uq_catalog_columns", "uq_catalog_coverage"} <= indexes


def test_freshness_shows_owners_last_scans_and_missing_assets(migrated_db: str) -> None:
    postgres, files, _ = _setup(migrated_db)
    rows = {str(r["system_id"]): r for r in freshness(migrated_db)}
    assert rows[postgres]["has_owner"] is True and rows[files]["has_owner"] is False
    assert rows[postgres]["last_scan_status"] == "completed"
    assert 1.9 <= float(rows[postgres]["hours_since_scan"]) <= 2.2
    assert rows[postgres]["missing_assets"] == 1
    assert (rows[files]["last_scan_at"], rows[files]["missing_assets"]) == (None, 0)


def test_treatments_are_linked_journaled_and_reconciled(migrated_db: str) -> None:
    postgres, files, store = _setup(migrated_db)
    summary = import_treatments(store, migrated_db, CSV, DPO)
    assert (summary.treatments, summary.links, summary.removed) == (2, 1, 0)
    declared = store.query(
        "MATCH (s:System)-[:DECLARED_IN]->(t:Treatment) RETURN s.id, t.id, t.legal_basis",
        columns=("system", "treatment", "basis"),
    )
    assert declared == [{"system": postgres, "treatment": "T-001", "basis": "GDPR 9.2.h"}]

    moved = CSV.replace(b"dev-source-postgres", files.encode("ascii"))
    again = import_treatments(store, migrated_db, moved, DPO)
    assert (again.treatments, again.links, again.removed) == (2, 1, 1)
    declared = store.query(
        "MATCH (s:System)-[:DECLARED_IN]->(t:Treatment) RETURN s.id, t.id",
        columns=("system", "treatment"),
    )
    assert declared == [{"system": files, "treatment": "T-001"}]
    assert len(store.query("MATCH (t:Treatment) RETURN t.key", columns=("key",))) == 2
    with psycopg.connect(migrated_db) as conn:
        entries = conn.execute(
            "SELECT actor, payload->>'treatments' FROM argos.audit_journal "
            "WHERE action = 'inventory.treatments_import' ORDER BY seq"
        ).fetchall()
    assert entries == [(DPO, "2"), (DPO, "2")]


@pytest.mark.parametrize(
    ("content", "actor", "message"),
    [
        (CSV.replace(b"dev-source-postgres", b"dev-unknown-system"), DPO, "unknown systems"),
        (CSV, "system:inventory", "user:"),
        (b"id;nombre\nT-1;x\n", DPO, "headers"),
    ],
)
def test_invalid_imports_write_nothing(
    migrated_db: str, content: bytes, actor: str, message: str
) -> None:
    _, _, store = _setup(migrated_db)
    with pytest.raises(ValueError, match=message):
        import_treatments(store, migrated_db, content, actor)
    assert store.query("MATCH (t:Treatment) RETURN t.key", columns=("key",)) == []
