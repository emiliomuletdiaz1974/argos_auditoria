"""ARG-046 · same inputs, same verdict bytes, on every machine (Plan Director §8.2, block 7).

The expected canonical bytes were written by hand before the evaluator exists; this suite runs in CI
(Linux) and locally (Windows), the two machines the plan asks for.
"""

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from argos_common.journal import canonicalize

CASES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "determinism"
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("*.json"))]
RESULTS = {"compliant", "non_compliant", "not_demonstrated", "inconclusive"}
PENDING = pytest.mark.xfail(
    raises=ModuleNotFoundError, strict=True, reason="argos_challenges.evaluator arrives in F05-09"
)


def _ids(case: dict[str, Any]) -> str:
    return str(case["name"])


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_float(v) for v in value)
    return False


def test_there_are_cases_for_every_result() -> None:
    results = {json.loads(case["expected_canonical"])["result"] for case in CASES}
    assert results == RESULTS
    assert len(CASES) >= 10


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_expected_bytes_are_canonical_float_free_and_hashed(case: dict[str, Any]) -> None:
    verdict = json.loads(case["expected_canonical"])
    assert canonicalize(verdict) == case["expected_canonical"]
    assert not _has_float(verdict) and not _has_float(case["unit"])
    digest = hashlib.sha256(case["expected_canonical"].encode("utf-8")).hexdigest()
    assert digest == case["expected_hash"]


@PENDING
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_evaluator_reproduces_the_expected_bytes(case: dict[str, Any]) -> None:
    evaluator = importlib.import_module("argos_challenges.evaluator")
    first = evaluator.evaluate(case["unit"], case["probe_result"], case["opa_decision"])
    second = evaluator.evaluate(case["unit"], case["probe_result"], case["opa_decision"])
    assert first.canonical() == second.canonical() == case["expected_canonical"]
    assert first.hash == case["expected_hash"]
