"""ARG-021 · closed vocabulary, deterministic natural keys and the AGE statement builder."""

import re

import pytest

from argos_inventory.graph.model import (
    CATEGORIES,
    EDGE_LABELS,
    NODE_LABELS,
    category_key,
    column_key,
    natural_key,
    schema_key,
    system_key,
    table_key,
)
from argos_inventory.graph.store import GraphStore, decode_agtype

SYSTEM_ID = "01920000-0000-7000-8000-00000000a001"


def test_vocabulary_is_closed_and_in_english() -> None:
    assert len(NODE_LABELS) == 10 and len(set(NODE_LABELS)) == 10
    assert len(EDGE_LABELS) == 8 and len(set(EDGE_LABELS)) == 8
    assert "personal_data" in CATEGORIES and "special_category.health" in CATEGORIES
    assert len(CATEGORIES) == 9 and all(re.fullmatch(r"[a-z_.]+", c) for c in CATEGORIES)


def test_natural_keys_are_deterministic_and_unambiguous() -> None:
    key = table_key(SYSTEM_ID, "clinic", "patients")
    assert key == table_key(SYSTEM_ID, "clinic", "patients")
    assert re.fullmatch(r"[0-9a-f]{40}", key)
    assert natural_key("ab", "c") != natural_key("a", "bc")
    assert table_key(SYSTEM_ID, "clinic", "patients") != schema_key(SYSTEM_ID, "clinic")
    assert column_key(SYSTEM_ID, "clinic", "patients", "id") != table_key(SYSTEM_ID, "clinic", "id")
    assert system_key(SYSTEM_ID) == natural_key("S", SYSTEM_ID)


def test_natural_keys_reject_ambiguous_parts() -> None:
    with pytest.raises(ValueError, match="separator"):
        natural_key("a\x1fb")
    with pytest.raises(ValueError, match="at least one"):
        natural_key()
    with pytest.raises(ValueError, match="unknown category"):
        category_key("dato_personal")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ('"k1"', "k1"),
        ("0.75", 0.75),
        ("5000", 5000),
        ('["a|0.5"]', ["a|0.5"]),
        ('{"key": "k"}', {"key": "k"}),
        (
            '{"id": 1, "label": "Table", "properties": {"key": "k"}}::vertex',
            {"id": 1, "label": "Table", "properties": {"key": "k"}},
        ),
    ],
)
def test_decode_agtype(raw: str | None, expected: object) -> None:
    assert decode_agtype(raw) == expected


def test_statement_builder_guards_the_dollar_quote_and_columns() -> None:
    store = GraphStore("postgresql://unused@127.0.0.1:1/unused")
    sql = store.statement("MATCH (t:Table) WHERE t.name =~ '.*50%' RETURN t.key", ["key"])
    assert sql.startswith("SELECT * FROM cypher('inventory', $$ MATCH")
    assert "50%%" in sql and sql.endswith('AS ("key" agtype)')
    assert store.statement("RETURN 1", ["table", "column"]).endswith(
        'AS ("table" agtype, "column" agtype)'
    )
    with pytest.raises(ValueError, match=r"\$\$"):
        store.statement("RETURN 1 $$) AS (v agtype); DROP TABLE argos.systems; --", ["v"])
    with pytest.raises(ValueError, match="columns"):
        store.statement("RETURN 1", ["v; DROP"])
    with pytest.raises(ValueError, match="columns"):
        store.statement("RETURN 1", [])
