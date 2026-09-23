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
        ("a|b\nc", "`a\\|b c`"),  # the client's text, shown as code (SEC-055)
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
        "| `dev\\|x` | 75.00 |",  # the client's text, as code (SEC-055)
    ]


def test_a_hostile_name_is_shown_as_code_not_rendered() -> None:
    """SEC-055: a column name is the client's text; the report shows it, never renders it."""
    cell = markdown_cell("<img src=x onerror=alert(1)>", ES)
    assert cell.startswith("`") and cell.endswith("`")
    assert "<img src=x onerror=alert(1)>" in cell
    assert "|" not in markdown_cell("a|b", ES).replace(r"\|", "")


def test_a_backtick_in_a_name_does_not_close_its_code_span() -> None:
    cell = markdown_cell("a`b", ES)
    assert cell.startswith("`` ") and cell.endswith(" ``")
