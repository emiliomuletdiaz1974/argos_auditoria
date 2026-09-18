"""ARG-057 · the three unbreakable rules of the drafter, without a database (F06-10).

1. No invented figure reaches the record.
2. The text never alters a verdict: it narrates on compliant or non-compliant, it does not argue.
3. Every piece is marked as generated, with the hash of its prompt.
"""

import pytest
from argos_ai.reports.writer import DraftRejectedError, check_finding_narrative, check_summary

SUMMARY_FIGURES = {"units": 166, "systems": 2, "findings": 6, "critical": 1}
VERDICTS = {"v-1", "v-2"}


def test_a_summary_that_only_quotes_its_data_holds() -> None:
    sections = [{"title": "Resumen", "body": "Se ejecutaron 166 unidades sobre 2 sistemas."}]
    check_summary(sections, SUMMARY_FIGURES, ["v-1"], VERDICTS)


def test_a_summary_with_an_invented_figure_is_rejected_naming_it() -> None:
    sections = [{"title": "Resumen", "body": "Se abrieron 9 hallazgos."}]
    with pytest.raises(DraftRejectedError, match="9"):
        check_summary(sections, SUMMARY_FIGURES, [], VERDICTS)


def test_the_figures_of_every_section_are_checked_including_the_titles() -> None:
    sections = [
        {"title": "Resumen", "body": "Se ejecutaron 166 unidades."},
        {"title": "Los 12 riesgos principales", "body": "Sin cambios."},
    ]
    with pytest.raises(DraftRejectedError, match="12"):
        check_summary(sections, SUMMARY_FIGURES, [], VERDICTS)


def test_a_summary_that_cites_a_verdict_of_another_campaign_is_rejected() -> None:
    """Quoting a verdict is allowed; quoting one that is not in this record is inventing it."""
    sections = [{"title": "Resumen", "body": "Sin cifras."}]
    with pytest.raises(DraftRejectedError, match="v-99"):
        check_summary(sections, SUMMARY_FIGURES, ["v-99"], VERDICTS)


def test_a_narrative_that_describes_its_finding_holds() -> None:
    check_finding_narrative(
        {
            "context": "El sistema no cifra las conexiones.",
            "impact": "Los datos viajan en claro.",
            "recommendation": "Activar ssl en el servidor.",
        },
        figures={"occurrences": 1},
    )


@pytest.mark.parametrize(
    "claim",
    [
        "En realidad el sistema es conforme.",
        "El hallazgo no procede: cumple con el artículo 32.",
        "Puede considerarse conforme a efectos prácticos.",
    ],
)
def test_a_narrative_that_argues_with_its_verdict_is_rejected(claim: str) -> None:
    """The finding comes from a non-compliant verdict: the drafter narrates it, never undoes it."""
    with pytest.raises(DraftRejectedError, match="veredicto"):
        check_finding_narrative(
            {"context": claim, "impact": "Ninguno.", "recommendation": "Ninguna."}, figures={}
        )


def test_a_narrative_with_an_invented_figure_is_rejected() -> None:
    with pytest.raises(DraftRejectedError, match="40"):
        check_finding_narrative(
            {"context": "Afecta a 40 pacientes.", "impact": "x", "recommendation": "y"},
            figures={"occurrences": 1},
        )


def test_a_narrative_may_say_what_its_verdict_says() -> None:
    """«No es conforme» is not arguing with the verdict: it is the verdict."""
    check_finding_narrative(
        {
            "context": "El sistema no es conforme con el artículo 32.",
            "impact": "No cumple el cifrado en tránsito.",
            "recommendation": "Activar ssl.",
        },
        figures={"occurrences": 1},
    )
