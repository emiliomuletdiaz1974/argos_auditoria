"""ARG-029 · pure pieces of the inventory API: cursors, page bounds and the selector compiler."""

import base64
from collections.abc import Callable
from typing import Any

import pytest

from argos_inventory.api.pagination import (
    MAX_PAGE_SIZE,
    after_key,
    after_offset,
    check_first,
    encode_cursor,
)
from argos_inventory.api.selector import ALLOWED_SELECTOR_FIELDS, compile_selector, parse_selector


def _raw_cursor(text: bytes) -> str:
    return base64.urlsafe_b64encode(text).decode("ascii")


def test_cursors_round_trip_and_are_opaque() -> None:
    assert after_key(encode_cursor("abc")) == "abc"
    assert after_offset(encode_cursor(40)) == 40
    assert after_key(None) is None
    assert after_offset(None) == 0
    assert "abc" not in encode_cursor("abc")


@pytest.mark.parametrize(
    ("decode", "cursor"),
    [
        (after_key, "%%%"),
        (after_key, encode_cursor(5)),
        (after_offset, encode_cursor("k")),
        (after_offset, _raw_cursor(b'{"v": -1}')),
        (after_offset, _raw_cursor(b'{"v": 1, "w": 2}')),
    ],
)
def test_invalid_cursors_are_rejected(decode: Callable[[str | None], Any], cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        decode(cursor)


@pytest.mark.parametrize("first", [0, -1, MAX_PAGE_SIZE + 1])
def test_page_size_is_bounded(first: int) -> None:
    with pytest.raises(ValueError, match="first"):
        check_first(first)


def test_largest_page_is_allowed() -> None:
    assert check_first(MAX_PAGE_SIZE) == 500


def test_selector_compiles_to_parameterised_cypher() -> None:
    selector = parse_selector(
        {
            "label": "Column",
            "category": "special_category",
            "min_confidence": 0.9,
            "missing": False,
            "name_like": "diag",
        }
    )
    cypher, params = compile_selector(selector, first=10, after="k1")
    assert cypher.startswith("MATCH (n:Column)-[r:CLASSIFIED_AS]->(k:Category) WHERE ")
    for clause in (
        "n.key > $after",
        "k.name STARTS WITH $category",
        "r.confidence >= $min_confidence",
        "coalesce(n.missing, false) = $missing",
        "n.name STARTS WITH $name_like",
    ):
        assert clause in cypher
    assert "WITH DISTINCT n WITH n ORDER BY n.key LIMIT 11 RETURN " in cypher
    assert params == {
        "after": "k1",
        "category": "special_category",
        "min_confidence": 0.9,
        "missing": False,
        "name_like": "diag",
    }


def test_default_label_and_system_kind_in_two_steps() -> None:
    selector = parse_selector({"system_kind": "rdbms"})
    assert (selector.label, selector.system_kind) == ("Column", "rdbms")
    cypher, params = compile_selector(selector, first=5, system_ids=["b", "a"])
    assert "MATCH (n:Column) WHERE coalesce(n.system_id, n.id) IN $system_ids" in cypher
    assert params == {"system_ids": ["a", "b"]}
    with pytest.raises(ValueError, match="system ids"):
        compile_selector(selector, first=5)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"label": "Column) DETACH DELETE n //"}, "unknown node label"),
        ({"label": "column"}, "unknown node label"),
        ({"owner": "x"}, "not allowed"),
        ({"name_like": "x" * 101}, "name_like"),
        ({"name_like": ""}, "name_like"),
        ({"min_confidence": 0.5}, "needs category"),
        ({"category": "personal_data", "min_confidence": 1.5}, "min_confidence"),
        ({"category": "personal_data", "min_confidence": True}, "min_confidence"),
        ({"missing": "no"}, "missing"),
    ],
)
def test_invalid_selectors_are_rejected(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_selector(raw)


def test_client_text_only_travels_as_parameters() -> None:
    hostile = "x' }) DETACH DELETE n //"
    selector = parse_selector({"label": "Table", "name_like": hostile, "category": hostile})
    cypher, params = compile_selector(selector, first=1)
    assert hostile not in cypher
    assert "DETACH" not in cypher
    assert params["name_like"] == hostile == params["category"]


def test_allowed_fields_are_the_documented_ones() -> None:
    assert {
        "label",
        "category",
        "system_kind",
        "min_confidence",
        "missing",
        "name_like",
        "unclassified",
        "status",
    } == ALLOWED_SELECTOR_FIELDS
