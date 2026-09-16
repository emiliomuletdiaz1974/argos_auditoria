"""ARG-026 · Markdown helpers of the inventory report (pure)."""

from decimal import Decimal

import pytest

from argos_inventory.catalog.report import LABELS, markdown_cell, markdown_table

ES = LABELS["es"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        (True, "sí"),
        (0.9, "0.90"),
        (Decimal("75.0"), "75.0"),
        ("a|b\nc", "a\\|b c"),
    ],
)
def test_markdown_cell(value: object, expected: str) -> None:
    assert markdown_cell(value, ES) == expected


def test_empty_tables_say_so() -> None:
    assert markdown_table(["A"], [], ES) == [ES["empty"]]


def test_tables_have_a_header_separator_and_escaped_rows() -> None:
    assert markdown_table(["Sistema", "Cobertura"], [["dev|x", 75.0]], ES) == [
        "| Sistema | Cobertura |",
        "|---|---|",
        "| dev\\|x | 75.00 |",
    ]
