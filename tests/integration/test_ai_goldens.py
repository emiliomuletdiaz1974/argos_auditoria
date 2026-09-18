"""ARG-059 · the golden sets through the whole pipeline, with the oracle as the model (F06-12).

What this measures is everything around the model: retrieval reaching the cited fragment, the
checks accepting what is right and refusing the traps, and the gate. The model itself is measured
with `--backend real`, as a release gate.
"""

import asyncio

import pytest
from argos_ai.evaluation.harness import evaluate_all
from argos_ai.evaluation.metrics import gate
from argos_ai.rag.embeddings import HashEmbedder

pytestmark = pytest.mark.integration


def test_every_suite_reaches_its_threshold_with_the_oracle(migrated_db: str) -> None:
    results = asyncio.run(evaluate_all(migrated_db, HashEmbedder()))
    for report in results:
        print(report.as_dict())
    below = {r.suite: r.as_dict() for r in results if not r.passed}
    assert below == {}
    assert gate(results) == 0


def test_the_report_traps_are_refused_even_with_the_oracle(migrated_db: str) -> None:
    """The oracle hands the verifier the trap drafts: refusing them is the verifier's work."""
    results = {r.suite: r for r in asyncio.run(evaluate_all(migrated_db, HashEmbedder()))}
    traps = [o for o in results["reports"].outcomes if o.kind == "trap"]
    assert traps and all(o.correct for o in traps)
