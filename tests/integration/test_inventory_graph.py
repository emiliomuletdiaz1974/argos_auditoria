"""ARG-021 · inventory graph on Apache AGE: vocabulary, unique natural keys, idempotent writes."""

import psycopg
import pytest

from argos_inventory.graph.model import (
    CATEGORIES,
    EDGE_LABELS,
    NODE_LABELS,
    category_key,
    table_key,
)
from argos_inventory.graph.store import GRAPH, GraphStore

pytestmark = pytest.mark.integration

SYSTEM_ID = "01920000-0000-7000-8000-00000000a001"
LABELS_SQL = (
    "SELECT l.name, l.kind FROM ag_catalog.ag_label l "
    "JOIN ag_catalog.ag_graph g ON g.graphid = l.graph WHERE g.name = %s"
)
UPSERT = (
    "MERGE (t:Table {key: $key}) SET t.name = $name "
    "SET t.first_seen = coalesce(t.first_seen, $now) SET t.last_seen = $now"
)


def test_migration_creates_the_closed_vocabulary(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(LABELS_SQL, (GRAPH,)).fetchall()
    own = [(name, kind) for name, kind in rows if not name.startswith("_ag_")]
    assert {name for name, kind in own if kind == "v"} == set(NODE_LABELS)
    assert {name for name, kind in own if kind == "e"} == set(EDGE_LABELS)


def test_root_categories_carry_their_natural_keys(migrated_db: str) -> None:
    rows = GraphStore(migrated_db).query(
        "MATCH (c:Category) RETURN c.name, c.key", columns=("name", "key")
    )
    assert {r["name"]: r["key"] for r in rows} == {c: category_key(c) for c in CATEGORIES}


def test_merge_is_idempotent_and_keeps_first_seen(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    key = table_key(SYSTEM_ID, "clinic", "patients")
    store.execute(UPSERT, {"key": key, "name": "patients", "now": "2026-09-15T00:00:00+00:00"})
    store.execute(UPSERT, {"key": key, "name": "patients", "now": "2026-09-16T00:00:00+00:00"})
    rows = store.query(
        "MATCH (t:Table {key: $key}) RETURN t.first_seen, t.last_seen",
        {"key": key},
        ("first_seen", "last_seen"),
    )
    assert rows == [
        {"first_seen": "2026-09-15T00:00:00+00:00", "last_seen": "2026-09-16T00:00:00+00:00"}
    ]


def test_unique_index_rejects_a_duplicate_natural_key(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    store.execute("CREATE (:Table {key: 'duplicate'})")
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.execute("CREATE (:Table {key: 'duplicate'})")


def test_batch_upsert_applies_every_set_clause_to_every_row(migrated_db: str) -> None:
    # Regression guard (deviation note ARG-021-023): one SET clause per property in UNWIND batches.
    store = GraphStore(migrated_db)
    rows = [{"key": f"c{i}", "name": f"col{i}"} for i in range(5)]
    batch = (
        "UNWIND $rows AS r MERGE (c:Column {key: r.key}) SET c.name = r.name "
        "SET c.first_seen = coalesce(c.first_seen, $now)"
    )
    store.execute(batch, {"rows": rows, "now": "t1"})
    store.execute(batch, {"rows": rows, "now": "t2"})
    found = store.query(
        "MATCH (c:Column) RETURN c.key, c.name, c.first_seen", columns=("key", "name", "first_seen")
    )
    expected = [{"key": f"c{i}", "name": f"col{i}", "first_seen": "t1"} for i in range(5)]
    assert sorted(found, key=lambda r: r["key"]) == expected


def test_existence_filter_and_parameter_types(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    store.execute("CREATE (:Table {key: 'k1', est_rows: 5000, ratio: 0.75})")
    rows = store.query(
        "MATCH (t:Table) WHERE NOT exists((t)-[:CLASSIFIED_AS]->()) AND t.est_rows > $min "
        "RETURN t.key, t.ratio, properties(t)",
        {"min": 1000},
        ("key", "ratio", "props"),
    )
    assert rows == [
        {"key": "k1", "ratio": 0.75, "props": {"key": "k1", "est_rows": 5000, "ratio": 0.75}}
    ]
