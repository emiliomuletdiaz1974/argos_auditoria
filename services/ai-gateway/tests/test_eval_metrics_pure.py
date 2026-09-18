"""ARG-059 · the harness turns outcomes into a score and a score into a gate (F06-12).

«The AI works well» is, in ARGOS, a claim with evidence. The traps weigh double because they
measure refusal, the hardest virtue; a suite that passes while failing every trap does not pass.
"""

import pytest
from argos_ai.evaluation.metrics import (
    TRAP_WEIGHT,
    EvaluationError,
    Outcome,
    SuiteReport,
    gate,
    score,
)


def _outcomes(plain: list[bool], traps: list[bool]) -> list[Outcome]:
    return [Outcome(f"p{n}", "plain", ok, "") for n, ok in enumerate(plain)] + [
        Outcome(f"t{n}", "trap", ok, "") for n, ok in enumerate(traps)
    ]


def test_the_score_is_worked_out_by_hand() -> None:
    """3 plain right of 4, 1 trap right of 2: (3 + 2·1) / (4 + 2·2) = 5/8."""
    assert TRAP_WEIGHT == 2
    assert score(_outcomes([True, True, True, False], [True, False])) == pytest.approx(5 / 8)


def test_a_trap_weighs_twice_a_plain_case() -> None:
    only_traps_fail = score(_outcomes([True] * 4, [False, False]))
    only_plain_fail = score(_outcomes([True, True, False, False], [True, True]))
    assert only_traps_fail < only_plain_fail


def test_a_suite_that_passes_the_plain_cases_and_fails_every_trap_does_not_pass() -> None:
    report = SuiteReport("rag", score(_outcomes([True] * 20, [False] * 4)), [], minimum=0.85)
    assert report.score == pytest.approx(20 / 28)
    assert gate([report]) == 1


def test_the_gate_opens_when_every_suite_reaches_its_threshold() -> None:
    reports = [
        SuiteReport("rag", 0.9, [], minimum=0.85),
        SuiteReport("reports", 1.0, [], minimum=1.0),
    ]
    assert gate(reports) == 0


def test_one_suite_below_its_threshold_closes_the_gate() -> None:
    reports = [
        SuiteReport("rag", 0.9, [], minimum=0.85),
        SuiteReport("reports", 0.99, [], minimum=1.0),
    ]
    assert gate(reports) == 1


def test_an_empty_suite_is_an_error_not_a_perfect_score() -> None:
    """Nothing measured is not everything right."""
    with pytest.raises(EvaluationError, match="no cases"):
        score([])


def test_a_threshold_without_its_suite_closes_the_gate() -> None:
    """The harness must not give as good what it did not measure."""
    with pytest.raises(EvaluationError, match="classify"):
        gate([SuiteReport("rag", 1.0, [], minimum=0.85)], expected={"rag", "classify"})
