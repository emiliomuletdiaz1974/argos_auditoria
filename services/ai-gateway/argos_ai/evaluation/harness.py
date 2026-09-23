"""Run every trade against its golden set and compare with the thresholds (ARG-059).

`evaluate_all` is what both the CI and `tools/ai_eval/run_goldens.py` call, so there is one way of
measuring. A suite that disappears, or a threshold without its suite, is an error: the harness does
not give as good what it did not measure.
"""

from collections.abc import Callable

from argos_ai.backends.base import Backend
from argos_ai.evaluation.goldens import SUITES, Case, load_goldens, load_thresholds
from argos_ai.evaluation.metrics import EvaluationError, Outcome, SuiteReport, score
from argos_ai.evaluation.runners import (
    index_corpus,
    oracle_backends,
    run_classify,
    run_generate,
    run_guardrails,
    run_rag,
    run_reports,
)
from argos_ai.rag.embeddings import Embedder

BackendChooser = Callable[[str], Callable[[Case], Backend]]


async def evaluate_all(
    dsn: str, embedder: Embedder, backends: BackendChooser = oracle_backends
) -> list[SuiteReport]:
    thresholds = load_thresholds()
    unknown = sorted(set(thresholds) - set(SUITES))
    if unknown:
        raise EvaluationError(f"thresholds for suites that do not exist: {unknown}")
    index_corpus(dsn, embedder)
    reports: list[SuiteReport] = []
    for suite in SUITES:
        if suite not in thresholds:
            raise EvaluationError(f"the suite {suite} has no threshold")
        cases = load_goldens(suite)
        backend_for = backends(suite)
        outcomes: list[Outcome]
        if suite == "rag":
            outcomes = await run_rag(cases, backend_for, dsn, embedder)
        elif suite == "classify":
            outcomes = await run_classify(cases, backend_for)
        elif suite == "generate":
            outcomes = await run_generate(cases, backend_for)
        elif suite == "guardrails":
            outcomes = run_guardrails(cases)
        else:
            outcomes = await run_reports(cases, backend_for)
        minimum = float(thresholds[suite]["minimum"])
        reports.append(SuiteReport(suite, score(outcomes), outcomes, minimum))
    return reports
