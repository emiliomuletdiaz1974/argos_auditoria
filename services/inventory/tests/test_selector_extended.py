"""ARG-029/033 · selector fields for unclassified columns and AI systems by status (pure)."""

from typing import Any

import pytest

from argos_inventory.api.selector import compile_selector, parse_selector


def test_unclassified_columns_compile_to_a_negated_existence_check() -> None:
    cypher, params = compile_selector(parse_selector({"unclassified": True}), first=10)
    assert "MATCH (n:Column) WHERE NOT exists((n)-[:CLASSIFIED_AS]->())" in cypher
    assert params == {}


def test_classified_columns_compile_to_an_existence_check() -> None:
    cypher, _ = compile_selector(parse_selector({"unclassified": False}), first=10)
    assert "WHERE exists((n)-[:CLASSIFIED_AS]->())" in cypher
    assert "NOT exists" not in cypher


def test_status_travels_as_a_parameter() -> None:
    hostile = "pending') DETACH DELETE n //"
    cypher, params = compile_selector(
        parse_selector({"label": "AISystem", "status": hostile}), first=5
    )
    assert "n.status STARTS WITH $status" in cypher
    assert hostile not in cypher
    assert params == {"status": hostile}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"unclassified": "yes"}, "unclassified must be a boolean"),
        ({"unclassified": True, "category": "personal_data"}, "cannot be combined"),
        ({"label": "AISystem", "status": ""}, "status"),
        ({"label": "AISystem", "status": 1}, "status"),
        ({"missing": "no"}, "missing must be a boolean"),
    ],
)
def test_invalid_extended_selectors_are_rejected(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_selector(raw)
