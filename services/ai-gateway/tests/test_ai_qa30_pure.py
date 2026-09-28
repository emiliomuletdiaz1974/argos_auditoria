"""Quality review QA-01 · the guardrails and the assistant in their edge cases (QA-30).

Each case is the scenario of the report (`docs/calidad/revision-qa-f01-f10.md`): a claim of
conformity or a write that slipped through, an identifier the scrubber did not see, a citation of
the RAG whose number and reference disagree, and a refusal that stated a figure nobody returned.
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
from argos_ai.rag.pipeline import CitationError, checked_citations

# ---------- QA-058 · a claim of conformity in ordinary words ----------


@pytest.mark.parametrize(
    "claim",
    [
        "Concluyo que cumple el RGPD",
        "El sistema es plenamente conforme con el RGPD",
        "The system is fully compliant with GDPR",
        "El sistema сumple el RGPD",  # Cyrillic es
        "No se aprecia ningún incumplimiento",
        "El tratamiento se ajusta al RGPD",
        "Entiendo que el sistema no cumple",
        "La réplica es totalmente conforme.",
        "Todo está conforme.",
    ],
)
def test_a_claim_of_conformity_in_ordinary_words_is_rejected(claim: str) -> None:
    with pytest.raises(OutputRejectedError, match="veredicto_no_citado"):
        check_output({"answer": claim})


@pytest.mark.parametrize(
    "text",
    [
        "El cumplimiento del artículo 32 exige cifrado; el responsable debe demostrarlo.",
        "Solo los tratamientos que incumplen la forma y su mensaje.",
        "Conforme al artículo 32, el responsable aplicará medidas técnicas apropiadas.",
        "El reto comprueba las columnas que cumplen el patrón de un DNI.",
        "El incumplimiento del artículo 33 obliga a notificar en 72 horas.",
    ],
)
def test_explaining_the_regulation_is_not_a_claim(text: str) -> None:
    assert check_output({"answer": text}) is True


# ---------- QA-059 · a write in valid SQL or shell ----------


@pytest.mark.parametrize(
    "write",
    [
        "UPDATE pacientes p SET activo=0",
        "DELETE pacientes WHERE id=1",
        "MERGE INTO pacientes USING x ON 1=1",
        "GRANT ALL ON pacientes TO app",
        "CREATE TABLE copia AS SELECT * FROM pacientes",
        "rm -rf /srv/data",
        "REVOKE SELECT ON pacientes FROM app",
        "UPDATE clinic.patients AS p SET dni = NULL",
    ],
)
def test_a_write_in_valid_sql_or_shell_is_rejected(write: str) -> None:
    with pytest.raises(OutputRejectedError, match="escritura_sobre_objetivo"):
        check_output({"answer": write})


@pytest.mark.parametrize(
    "innocent",
    [
        "Conviene revisar quién puede borrar datos del sistema.",
        "La columna updated_at registra la última modificación.",
        "El reto usa SELECT count(*) FROM clinic.patients.",
    ],
)
def test_talking_about_writes_is_not_a_write(innocent: str) -> None:
    assert check_output({"answer": innocent}) is True


# ---------- QA-071 · identifiers the scrubber did not see ----------


@pytest.mark.parametrize(
    ("text", "digits"),
    [
        ("DNI 12-345-678-Z", "12345678"),
        ("DNI 12345678​Z", "12345678"),
        ("IBAN ES91.2100.0418.4502.0005.1332", "9121000418450200051332"),
    ],
)
def test_an_identifier_written_with_other_separators_is_scrubbed(text: str, digits: str) -> None:
    clean, substitutions = scrub_input(text)
    assert substitutions == 1, clean
    assert digits not in "".join(ch for ch in clean if ch.isdigit())


# ---------- QA-068 · the number of a RAG citation is its fragment ----------


def test_a_citation_whose_number_is_another_fragment_is_refused() -> None:
    allowed = ["RGPD art. 32.1.a", "RGPD art. 33.1"]
    with pytest.raises(CitationError):
        checked_citations([{"n": 1, "reference": "RGPD art. 33.1"}], allowed)
    with pytest.raises(CitationError):
        checked_citations([{"n": 3, "reference": "RGPD art. 33.1"}], allowed)
    assert checked_citations([{"n": 2, "reference": "RGPD art. 33.1"}], allowed) == [
        "RGPD art. 33.1"
    ]


# ---------- QA-070 · a refusal is held to the figures too ----------


def _ask(replies: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> Any:
    def answering(name: str) -> Tool:
        return Tool(name, TOOL_SCHEMAS[name], lambda _arguments: results.get(name, {}))

    backend = FakeBackend.of([json.dumps(reply) for reply in replies])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"assistant": 1_000_000}
    )
    toolbox = {name: answering(name) for name in TOOL_SCHEMAS}
    return asyncio.run(ask("¿cuántos hallazgos críticos hay?", gateway, toolbox))


def test_a_refusal_that_states_a_figure_nobody_returned_is_not_an_answer() -> None:
    replies: list[dict[str, Any]] = [
        {"action": "tool", "tool": "finding_status", "arguments": {}},
        {"action": "refuse", "answer": "No lo sé, aunque hay 7 hallazgos críticos."},
    ]
    with pytest.raises(AssistantError, match="7"):
        _ask(replies, {"finding_status": {"total": 3}})


def test_an_honest_refusal_still_passes() -> None:
    replies: list[dict[str, Any]] = [
        {"action": "tool", "tool": "finding_status", "arguments": {}},
        {"action": "refuse", "answer": "Lo consultado no basta: hay 3 hallazgos y nada más."},
    ]
    assert _ask(replies, {"finding_status": {"total": 3}}).refused is True
