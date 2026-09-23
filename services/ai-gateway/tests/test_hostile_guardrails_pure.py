"""ARG-057/058/060 · the hostile cases of the security review F09-02 (SEC-032…035, SEC-049).

Each case is the exact input that got through before: a DNI glued to an underscore, an IBAN with
spaces, a claim of conformity with a zero-width space or without its accent, a percentage with a
decimal point, a range, a column called `last_update`. They fail on the old guardrails and hold now.
"""

import asyncio
import json
from typing import Any

import pytest
from argos_ai.assistant.agent import AssistantError, ask
from argos_ai.assistant.tools import TOOL_SCHEMAS, Tool
from argos_ai.backends.fake import FakeBackend
from argos_ai.gateway import Gateway
from argos_ai.guardrails import OutputRejectedError, check_output, scrub_input
from argos_ai.reports.figures import unsupported_figures

DNI = "12345678Z"  # the letter is the real one for these digits
NIE = "X1234567L"
IBAN = "ES9121000418450200051332"
NUSS = "281234567840"


# ---------- SEC-032 · no identifier reaches the model through a separator ----------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (f"dni_{DNI}", DNI),
        (f"columna{DNI}fin", DNI),
        ("12.345.678-Z", DNI),
        ("12345678 Z", DNI),
        ("X-1234567-L", NIE),
        ("ES91 2100 0418 4502 0005 1332", IBAN),
        ("ES91-2100-0418-4502-0005-1332", IBAN),
        ("28/12345678/40", NUSS),
        ("28 12345678 40", NUSS),
    ],
)
def test_an_identifier_with_separators_or_glued_is_scrubbed(text: str, value: str) -> None:
    clean, substitutions = scrub_input(f"el valor {text} aparece")
    assert substitutions == 1, clean
    digits = "".join(ch for ch in value if ch.isdigit())
    assert digits not in "".join(ch for ch in clean if ch.isdigit())


def test_an_invalid_lookalike_with_separators_is_left_alone() -> None:
    """The validator still decides: a reference that looks like a DNI is not destroyed."""
    text = "pedido 12.345.678-A"  # wrong control letter
    assert scrub_input(text) == (text, 0)


# ---------- SEC-034 · a claim of conformity in any spelling ----------


@pytest.mark.parametrize(
    "claim",
    [
        "El sistema cumple el artículo 32.",
        "La tabla incumple el artículo 5.",
        "El sistema es\u200bconforme con el RGPD.",
        "El sistema es conforme",
        "La replica esta en conformidad con el reglamento.",
        "Los sistemas resultan conformes.",
        "Ｅｓ conforme",  # full-width letters, NFKC folds them
        "The system is compliant with GDPR.",
        "The database complies with article 32.",
        "The system is non-compliant.",
    ],
)
def test_a_claim_of_conformity_is_rejected_whatever_its_spelling(claim: str) -> None:
    with pytest.raises(OutputRejectedError, match="veredicto_no_citado"):
        check_output({"answer": claim})


@pytest.mark.parametrize(
    "text",
    [
        "El cumplimiento del artículo 32 exige cifrado; el responsable debe demostrarlo.",
        "Solo los tratamientos que incumplen la forma y su mensaje.",
    ],
)
def test_explaining_the_law_or_a_criterion_is_not_a_claim(text: str) -> None:
    assert check_output({"answer": text}) is True


def test_a_verdict_is_citable_only_if_the_tools_returned_it() -> None:
    answer = {"answer": "El sistema es conforme.", "verdict_id": "v-1"}
    with pytest.raises(OutputRejectedError, match="veredicto_no_citado"):
        check_output(answer, lambda _: True, allowed_verdicts=frozenset({"v-2"}))
    assert check_output(answer, lambda _: True, allowed_verdicts=frozenset({"v-1"})) is True


# ---------- SEC-049 · a write is a statement, not a substring ----------


@pytest.mark.parametrize(
    "innocent",
    [
        "La columna last_update no tiene categoría.",
        "El campo updated_at se actualiza en cada alta.",
        "El texto aparece truncated en el informe.",
    ],
)
def test_a_column_name_is_not_a_write(innocent: str) -> None:
    assert check_output({"answer": innocent}) is True


@pytest.mark.parametrize(
    "write",
    [
        "Ejecuta UPDATE clinic.patients SET dni = NULL",
        "update pacientes set nombre = 'x'",
        "TRUNCATE TABLE billing.invoices",
        "delete from clinic.patients where id = 1",
    ],
)
def test_a_write_statement_is_still_rejected(write: str) -> None:
    with pytest.raises(OutputRejectedError, match="escritura_sobre_objetivo"):
        check_output({"answer": write})


# ---------- SEC-035 · every figure of a report is extracted ----------


@pytest.mark.parametrize(
    ("text", "offending"),
    [
        ("El 97.3 % de las columnas está clasificado.", ["97.3"]),
        ("Entre 15-20 tablas sin categoría.", ["15", "20"]),
        ("Hay 30días de retraso.", ["30"]),
        ("Una ratio de 0,85 en la réplica.", ["0,85"]),
        ("Se revisaron cuarenta sistemas.", ["cuarenta"]),
    ],
)
def test_an_invented_figure_is_found_however_it_is_written(text: str, offending: list[str]) -> None:
    assert unsupported_figures(text, [12, 3]) == offending


def test_supported_figures_in_the_new_shapes_hold() -> None:
    assert unsupported_figures("El 97.3 % y entre 15-20 tablas.", [0.973, 15, 20]) == []


def test_identifiers_and_dates_are_still_not_figures() -> None:
    text = "OBL-RGPD-32-1 y sec-encryption-at-rest, revisado el 2026-09-23 (F09-28)."
    assert unsupported_figures(text, []) == []


# ---------- SEC-033 · the assistant's figures and citations are its tools' ----------


def _toolbox(results: dict[str, dict[str, Any]]) -> dict[str, Tool]:
    def answering(name: str) -> Tool:
        def run(_arguments: dict[str, Any]) -> dict[str, Any]:
            return results.get(name, {})

        return Tool(name, TOOL_SCHEMAS[name], run)

    return {name: answering(name) for name in TOOL_SCHEMAS}


def _ask(replies: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> Any:
    backend = FakeBackend.of([json.dumps(reply) for reply in replies])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"assistant": 1_000_000}
    )
    return asyncio.run(ask("¿cuántos hallazgos críticos hay?", gateway, _toolbox(results)))


FINDINGS = {"finding_status": {"total": 3, "by_status_and_severity": [{"count": 3}]}}
REGULATION = {
    "search_regulation": {
        "fragments": [{"reference": "RGPD art. 33.1", "text": "en un plazo de 72 horas"}]
    }
}


def test_a_figure_no_tool_returned_is_refused() -> None:
    replies: list[dict[str, Any]] = [
        {"action": "tool", "tool": "finding_status", "arguments": {}},
        {
            "action": "answer",
            "answer": "Hay 7 hallazgos críticos [1].",
            "sources": [{"tool": "finding_status", "detail": "recuento"}],
        },
    ]
    with pytest.raises(AssistantError, match="7"):
        _ask(replies, FINDINGS)


def test_figures_from_the_tools_and_the_retrieved_text_hold() -> None:
    replies: list[dict[str, Any]] = [
        {"action": "tool", "tool": "finding_status", "arguments": {}},
        {"action": "tool", "tool": "search_regulation", "arguments": {"question": "brecha"}},
        {
            "action": "answer",
            "answer": "Hay 3 hallazgos [1] y la brecha se notifica en 72 horas [2].",
            "sources": [
                {"tool": "finding_status", "detail": "recuento"},
                {"tool": "search_regulation", "detail": "RGPD art. 33.1"},
            ],
        },
    ]
    result = _ask(replies, {**FINDINGS, **REGULATION})
    assert result.complete is True


def test_a_normative_source_must_be_a_fragment_it_retrieved() -> None:
    replies: list[dict[str, Any]] = [
        {"action": "tool", "tool": "search_regulation", "arguments": {"question": "brecha"}},
        {
            "action": "answer",
            "answer": "Se notifica sin dilación [1].",
            "sources": [{"tool": "search_regulation", "detail": "RGPD art. 99"}],
        },
    ]
    with pytest.raises(AssistantError, match="RGPD art. 99"):
        _ask(replies, REGULATION)
