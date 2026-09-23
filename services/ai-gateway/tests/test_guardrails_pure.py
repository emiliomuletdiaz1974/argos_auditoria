"""ARG-060 · the guardrails, pure and without a model (F06-03).

Two prohibitions, defended in depth. On the way in, no personal datum reaches a prompt; on the way
out, no answer decides conformity or asks for a write. Neither of them is a setting.
"""

import pytest
from argos_ai.guardrails import (
    OutputRejectedError,
    check_output,
    load_patterns,
    scrub_input,
)

# Synthetic identifiers that pass their validator: the DNI letter and the IBAN checksum are real.
DNI = "99992001F"
NIE = "X1234567L"
IBAN = "ES9121000418450200051332"


def test_a_real_identifier_is_replaced_by_a_stable_marker() -> None:
    clean, substitutions = scrub_input(f"La columna dni contiene {DNI}")
    assert DNI not in clean
    assert "[DNI-1]" in clean
    assert substitutions == 1


def test_the_same_value_twice_gets_the_same_marker() -> None:
    """A different marker each time would destroy the meaning of the text for the model."""
    clean, substitutions = scrub_input(f"{DNI} aparece y {DNI} vuelve a aparecer")
    assert clean.count("[DNI-1]") == 2
    assert substitutions == 2


def test_two_different_values_get_two_markers() -> None:
    clean, _ = scrub_input(f"{DNI} y {NIE}")
    assert "[DNI-1]" in clean and "[NIE-1]" in clean


@pytest.mark.parametrize(("value", "marker"), [(DNI, "DNI"), (NIE, "NIE"), (IBAN, "IBAN")])
def test_every_kind_of_identifier_is_recognised(value: str, marker: str) -> None:
    clean, substitutions = scrub_input(f"valor: {value}")
    assert value not in clean and f"[{marker}-1]" in clean
    assert substitutions == 1


def test_an_innocent_code_that_looks_like_an_identifier_is_left_alone() -> None:
    """Only what validates is replaced: otherwise a product code would be destroyed."""
    innocent = "12345678A"  # right shape, wrong control letter (the real one is Z)
    clean, substitutions = scrub_input(f"referencia {innocent}")
    assert clean == f"referencia {innocent}"
    assert substitutions == 0


def test_a_text_without_personal_data_comes_back_untouched() -> None:
    text = "La tabla clinic.patients tiene 3181 filas fuera de plazo."
    assert scrub_input(text) == (text, 0)


def test_a_claim_of_conformity_without_a_verdict_is_rejected() -> None:
    with pytest.raises(OutputRejectedError, match="veredicto_no_citado"):
        check_output({"answer": "El sistema clinic es conforme con el artículo 32."})


def test_a_claim_of_conformity_that_cites_its_verdict_is_allowed() -> None:
    """ARG-057 narrates verdicts that exist: quoting one is its job."""
    assert check_output(
        {
            "answer": "El sistema clinic no es conforme con el artículo 32.",
            "verdict_id": "01920000-0000-7000-8000-0000000000aa",
        }
    )


KNOWN = "01920000-0000-7000-8000-0000000000aa"


@pytest.mark.parametrize(
    "citation",
    [
        {"verdict_id": "01920000-0000-7000-8000-00000000dead"},
        {"verdict_id": "x"},
        {"verdict_ids": [KNOWN, "01920000-0000-7000-8000-00000000dead"]},
    ],
)
def test_a_citation_of_a_verdict_that_does_not_exist_is_no_citation(
    citation: dict[str, object],
) -> None:
    # Any truthy verdict_id used to switch the check off; the model can invent one.
    answer = {"answer": "El sistema clinic es conforme con el artículo 32.", **citation}
    with pytest.raises(OutputRejectedError, match="veredicto_no_citado"):
        check_output(answer, verdict_exists=lambda verdict_id: verdict_id == KNOWN)


def test_a_citation_of_verdicts_that_exist_is_allowed() -> None:
    answer = {"answer": "El sistema clinic no es conforme.", "verdict_ids": [KNOWN]}
    assert check_output(answer, verdict_exists=lambda verdict_id: verdict_id == KNOWN)


@pytest.mark.parametrize(
    "answer",
    [
        "Ejecuta DROP TABLE clinic.patients para resolverlo.",
        "Basta con un DELETE FROM argos.findings.",
        "Puedes modificar la tabla clinic.patients y listo.",
        "UPDATE billing.invoices SET status = 'ok'",
    ],
)
def test_an_instruction_to_write_on_a_system_is_rejected(answer: str) -> None:
    with pytest.raises(OutputRejectedError, match="escritura_sobre_objetivo"):
        check_output({"answer": answer})


def test_the_check_reaches_nested_text() -> None:
    """The rejection is not fooled by putting the sentence one level down."""
    with pytest.raises(OutputRejectedError):
        check_output({"sections": [{"title": "Resumen", "body": "El HIS es conforme."}]})


def test_recommending_encryption_is_not_an_instruction_to_write() -> None:
    assert check_output({"answer": "Se recomienda activar el cifrado en tránsito del servidor."})


def test_the_patterns_are_content_not_code() -> None:
    """The team widens the tables without a release: they travel with the prompt-pack."""
    patterns = load_patterns()
    assert patterns["verdict_patterns"] and patterns["write_patterns"]
    assert all(entry.strip() for entry in patterns["write_patterns"])
