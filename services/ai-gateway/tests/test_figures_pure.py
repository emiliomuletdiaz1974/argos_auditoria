"""ARG-057 · no invented figure reaches the record (F06-10).

The verifier extracts every number of a draft and checks it against the numbers of the data the
draft was written from. The golden cases of F06-02 are run as they are: they were written before
the verifier, so they cannot have been adjusted to it.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from argos_ai.reports.figures import extract_figures, unsupported_figures

GOLDEN_FILE = Path(__file__).resolve().parents[3] / "goldens" / "reports" / "figures.jsonl"
GOLDEN: list[dict[str, Any]] = [
    json.loads(line) for line in GOLDEN_FILE.read_text(encoding="utf-8").splitlines() if line
]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_the_golden_report_cases(case: dict[str, Any]) -> None:
    figures = case["input"]["figures"]
    draft = case["input"]["draft"]
    expected = case["expected"]
    found = unsupported_figures(draft, figures.values())
    if expected["accepted"]:
        assert found == []
    else:
        assert expected["offending"] in found


def test_a_spanish_thousands_separator_is_one_number() -> None:
    assert extract_figures("Se ejecutaron 1.200 unidades") == [("1.200", 1200.0, False)]


def test_a_decimal_comma_is_a_decimal() -> None:
    assert extract_figures("una media de 0,85 por sistema") == [("0,85", 0.85, False)]


def test_a_percentage_can_be_quoted_from_a_ratio_in_the_data() -> None:
    """«85 %» may quote 0.85: same figure, different format. Rejecting it is a false positive."""
    assert unsupported_figures("una cobertura del 85 %", [0.85]) == []
    assert unsupported_figures("una cobertura del 85 por ciento", [0.85]) == []


def test_arithmetic_done_by_the_model_is_not_accepted() -> None:
    """120 of 166 is 72.29 %: correct, and still refused. The verifier only accepts the data."""
    assert unsupported_figures("el 72,3 % resultaron conformes", [166, 120]) == ["72,3"]


def test_numbers_inside_identifiers_are_not_figures() -> None:
    """An obligation id or a challenge name is not a claim about quantities."""
    text = "El reto sec-encryption-at-rest verifica OBL-RGPD-32-1 en ret-table-retention."
    assert extract_figures(text) == []


def test_a_text_without_numbers_is_accepted() -> None:
    assert unsupported_figures("Se recomienda revisar el cifrado.", []) == []


def test_every_offending_figure_is_reported_not_just_the_first() -> None:
    assert unsupported_figures("3 sistemas, 7 hallazgos y 9 retos", [3]) == ["7", "9"]


@pytest.mark.parametrize(
    "text",
    [
        "El sistema no es conforme con el artículo 32.",
        "Lo exige el art. 32.1.a del RGPD.",
        "Según el apartado 2 y el considerando 39.",
        "Véase el anexo III y el artículo 9.",
    ],
)
def test_a_legal_reference_is_not_a_figure(text: str) -> None:
    """«Artículo 32» names a place in a law; it says nothing about quantities."""
    assert unsupported_figures(text, []) == []


def test_a_figure_next_to_a_reference_is_still_checked() -> None:
    assert unsupported_figures("El artículo 32 afecta a 40 sistemas.", []) == ["40"]
