"""Graph write performance · indexes AGE really uses and bounded connections (task F03-15)."""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-15T10:00:00+00:00"
BULK = 200
BULK_COLUMNS = (
    "UNWIND $columns AS c "
    "CREATE (:Column {key: c.key, name: c.name, qualified_name: c.name, system_id: c.sid})"
)


def _plan(store: GraphStore, cypher: str, params: dict[str, Any]) -> str:
    """Plan with sequential scans disabled: only an index that can serve the lookup avoids one.

    On a small test graph the planner rightly prefers a sequential scan, so the test checks that a
    usable index exists; without one PostgreSQL keeps the sequential scan even when disabled.
    """
    sql = "EXPLAIN " + store.statement(cypher, ("v",))
    with store.connection() as conn:
        conn.execute("SET LOCAL enable_seqscan = off")
        rows = conn.execute(sql, (json.dumps(params),)).fetchall()
    return "\n".join(str(r[0]) for r in rows)


@pytest.mark.parametrize(
    ("label", "prop"),
    [("Column", "key"), ("Table", "key"), ("Column", "system_id"), ("System", "id")],
)
def test_property_lookups_use_an_index(migrated_db: str, label: str, prop: str) -> None:
    store = GraphStore(migrated_db)
    columns = [{"key": f"bulk-{i:05d}", "name": f"c{i}", "sid": f"s{i % 50}"} for i in range(BULK)]
    store.execute(BULK_COLUMNS, {"columns": columns})
    store.execute(
        "UNWIND $rows AS r CREATE (:Table {key: r, name: r, system_id: 's0'})",
        {"rows": [f"table-{i:05d}" for i in range(BULK)]},
    )
    store.execute(
        "UNWIND $rows AS r CREATE (:System {key: r, id: r, name: r})",
        {"rows": [f"sys-{i:05d}" for i in range(BULK)]},
    )
    value = {"key": "bulk-01234", "system_id": "s7", "id": "sys-01234"}[prop]
    if label == "Table":
        value = "table-01234"
    plan = _plan(store, f"MATCH (n:{label} {{{prop}: $v}}) RETURN n.key", {"v": value})
    assert "Index Scan" in plan, plan
    assert f'Seq Scan on "{label}"' not in plan, plan


@pytest.fixture
def counted_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    opened: list[str] = []
    original = psycopg.connect

    def counting(*args: Any, **kwargs: Any) -> Any:
        opened.append(str(args[0]) if args else "")
        return original(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counting)
    yield opened


def _never(system_id: str, spec: ProbeSpec) -> ProbeResult:
    raise AssertionError("dictionary-only classification must not probe")


def _ingest_table(dsn: str, system_id: str, table: str, columns: int) -> None:
    names = ["national_id", "email", "full_name", "diagnosis_code", "iban"]
    data = {
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
        "columns": [
            {"name": f"{names[i % len(names)]}_{i}", "type": "text", "nullable": True}
            for i in range(columns)
        ],
    }
    ingestor = Ingestor(GraphStore(dsn), dsn, RecordingBus())
    asyncio.run(ingestor.handle(data, {"type": "eu.argos.discovery.table_found.v1"}))


@pytest.mark.parametrize("columns", [5, 50])
def test_classification_connections_do_not_grow_with_columns(
    migrated_db: str, counted_connections: list[str], columns: int
) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    _ingest_table(migrated_db, system_id, "wide", columns)
    counted_connections.clear()
    summary = classify_new_columns(
        GraphStore(migrated_db), _never, system_id, available=frozenset()
    )
    assert summary.dictionary >= 1
    assert len(counted_connections) <= 3, counted_connections


def test_reingesting_a_table_updates_columns_without_per_column_merges(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    _ingest_table(migrated_db, system_id, "wide", 10)
    sent: list[str] = []
    original = GraphStore.query

    def recording(self: GraphStore, cypher: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(cypher)
        return original(self, cypher, *args, **kwargs)

    monkeypatch.setattr(GraphStore, "query", recording)
    _ingest_table(migrated_db, system_id, "wide", 11)  # ten known columns and a new one
    monkeypatch.undo()

    assert not any("MERGE (col:Column" in s for s in sent), sent
    assert not any("MERGE (t)-[:CONTAINS]->(col)" in s for s in sent), sent
    store = GraphStore(migrated_db)
    [linked] = store.query(
        "MATCH (t:Table {name: 'wide'})-[r:CONTAINS]->(c:Column) RETURN count(r)", columns=("n",)
    )
    assert linked["n"] == 11
    [unique] = store.query(
        "MATCH (c:Column) RETURN count(DISTINCT c.key), count(c)", columns=("keys", "nodes")
    )
    assert unique["keys"] == unique["nodes"] == 11
    firsts = store.query(
        "MATCH (c:Column) WHERE c.first_seen IS NULL OR c.last_seen IS NULL RETURN c.key",
        columns=("k",),
    )
    assert firsts == []


@pytest.mark.parametrize("columns", [5, 50])
def test_classification_statements_do_not_grow_with_columns(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch, columns: int
) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    _ingest_table(migrated_db, system_id, "wide", columns)
    sent: list[str] = []
    original = GraphStore.query

    def recording(self: GraphStore, cypher: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(cypher)
        return original(self, cypher, *args, **kwargs)

    monkeypatch.setattr(GraphStore, "query", recording)
    summary = classify_new_columns(
        GraphStore(migrated_db), _never, system_id, available=frozenset()
    )
    monkeypatch.undo()
    assert summary.dictionary >= 1
    assert len(sent) <= 3, sent
    [edges] = GraphStore(migrated_db).query(
        "MATCH (:Column)-[r:CLASSIFIED_AS]->(:Category) RETURN count(r)", columns=("n",)
    )
    assert edges["n"] == summary.dictionary
