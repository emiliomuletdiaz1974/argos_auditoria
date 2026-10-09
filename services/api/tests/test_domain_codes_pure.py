"""Every refusal of the campaign engine reaches the person in Spanish, not English (ARG-071).

The engine raises `CampaignStateError` and `SyntheticError` with a stable `code`; the API turns
that code into its own and writes the detail. A raise without a code, or a code the API does not
know, would put the engine's English in front of the person: both break here.
"""

import ast
from pathlib import Path

import pytest

from argos_api.errors import DOMAIN_ERRORS, ErrorCode, domain_error
from argos_challenges.store import CampaignStateError
from argos_challenges.synthetic import SyntheticError

ENGINE = Path(__file__).resolve().parents[2] / "challenge-engine" / "argos_challenges"
REFUSALS = {"CampaignStateError", "SyntheticError"}


def _raises(path: Path) -> list[ast.Call]:
    calls = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name) and func.id in REFUSALS:
                calls.append(node.exc)
    return calls


def _codes() -> list[tuple[str, int, str]]:
    found = []
    for name in ("store.py", "synthetic.py"):
        for call in _raises(ENGINE / name):
            codes = [k.value for k in call.keywords if k.arg == "code"] + call.args[1:2]
            value = codes[0].value if codes and isinstance(codes[0], ast.Constant) else None
            found.append((name, call.lineno, str(value)))
    return found


def test_the_engine_raises_its_refusals_somewhere() -> None:
    assert len(_codes()) >= 25


@pytest.mark.parametrize(("module", "line", "code"), _codes())
def test_every_refusal_of_the_engine_has_a_code_the_api_knows(
    module: str, line: int, code: str
) -> None:
    assert code in DOMAIN_ERRORS, f"{module}:{line} raises without a code the API translates"


def test_every_api_code_of_the_engine_is_in_the_catalogue() -> None:
    for status, code, detail in DOMAIN_ERRORS.values():
        assert isinstance(code, ErrorCode)
        assert 400 <= status < 600
        assert detail[0].isupper() and detail.endswith(".")


def test_the_detail_is_written_with_the_data_of_the_occurrence() -> None:
    error = domain_error(
        CampaignStateError(
            "the gate start was not requested", "gate_not_requested", {"gate": "start"}
        )
    )
    assert (error.status_code, error.code) == (409, ErrorCode.GATE_NOT_REQUESTED)
    assert error.detail == "La compuerta «Inicio de la campaña» no se ha solicitado."


def test_a_closed_campaign_names_its_state_in_spanish() -> None:
    error = domain_error(CampaignStateError("closed", "campaign_closed", {"status": "sealed"}))
    assert error.detail == "La campaña está sellada y no admite más aprobaciones."


def test_a_code_the_api_does_not_know_answers_a_generic_spanish_conflict() -> None:
    error = domain_error(SyntheticError("something new", "brand_new"))
    assert (error.status_code, error.code) == (409, ErrorCode.CONFLICT)
    assert "something new" not in str(error.detail)


def test_a_missing_value_in_the_details_does_not_break_the_answer() -> None:
    error = domain_error(CampaignStateError("no gate", "gate_not_requested"))
    assert error.status_code == 409
    assert "{" not in str(error.detail)
