"""Scores and the gate of the AI layer (ARG-059).

Every trade answers each golden case right or wrong; a suite's score is the weighted share of right
answers, and the gate compares it with the threshold written, with its reason, in
`goldens/thresholds.yaml`. The traps weigh double: they measure refusal —not inventing a figure,
saying the corpus does not cover a question, leaving a doubtful column alone— which is the hardest
virtue and the one that costs most when it is missing.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from argos_common.errors import ArgosError

TRAP_WEIGHT = 2


class EvaluationError(ArgosError):
    """The harness cannot give a score it did not measure."""


@dataclass(frozen=True, slots=True)
class Outcome:
    case_id: str
    kind: str
    correct: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SuiteReport:
    suite: str
    score: float
    outcomes: list[Outcome] = field(default_factory=list)
    minimum: float = 1.0

    @property
    def passed(self) -> bool:
        return self.score >= self.minimum

    def as_dict(self) -> dict[str, object]:
        return {
            "suite": self.suite,
            "score": round(self.score, 4),
            "minimum": self.minimum,
            "passed": self.passed,
            "failed_cases": [o.case_id for o in self.outcomes if not o.correct],
        }


def score(outcomes: Sequence[Outcome]) -> float:
    """The weighted share of right answers. Nothing measured is an error, not a perfect score."""
    if not outcomes:
        raise EvaluationError("a suite with no cases cannot be scored")
    weights = [TRAP_WEIGHT if outcome.kind == "trap" else 1 for outcome in outcomes]
    right = sum(w for w, outcome in zip(weights, outcomes, strict=True) if outcome.correct)
    return right / sum(weights)


def gate(reports: Iterable[SuiteReport], expected: set[str] | None = None) -> int:
    """0 if every suite reaches its threshold, 1 otherwise: the exit code of the CI step."""
    reports = list(reports)
    measured = {report.suite for report in reports}
    missing = sorted((expected or set()) - measured)
    if missing:
        raise EvaluationError(f"suites with a threshold but no measurement: {missing}")
    return 0 if all(report.passed for report in reports) else 1
