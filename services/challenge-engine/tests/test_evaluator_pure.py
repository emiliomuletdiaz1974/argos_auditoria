"""ARG-046 · the evaluator beyond the determinism suite: every operator and every closed way."""

from typing import Any

import pytest

from argos_challenges.evaluator import OPERATORS, RESULTS, evaluate

UNIT: dict[str, Any] = {
    "unit_id": "u-1",
    "challenge_id": "sec-encryption-in-transit",
    "challenge_version": "1.0",
    "node_key": "k-1",
    "criterion": {"threshold": {"field": "count", "operator": "<=", "value": 10}},
    "sampling": None,
}


def _unit(**changes: Any) -> dict[str, Any]:
    return {**UNIT, **changes}


def _threshold(operator_name: str, value: Any, observed: Any) -> str:
    unit = _unit(criterion={"threshold": {"field": "v", "operator": operator_name, "value": value}})
    return evaluate(unit, {"ok": True, "data": {"v": observed}}).result


@pytest.mark.parametrize("name", sorted(OPERATORS))
def test_every_operator_decides_both_ways(name: str) -> None:
    results = {_threshold(name, 5, observed) for observed in (3, 5, 7)}
    assert results == {"compliant", "non_compliant"}


def test_a_path_with_indices_is_resolved() -> None:
    unit = _unit(criterion={"threshold": {"field": "rows.1.ssl", "operator": "==", "value": "on"}})
    data = {"rows": [{"ssl": "off"}, {"ssl": "on"}]}
    assert evaluate(unit, {"ok": True, "data": data}).result == "compliant"


@pytest.mark.parametrize(
    "data",
    [{"rows": []}, {"rows": [{"other": 1}]}, {"rows": "on"}, {}],
)
def test_evidence_that_does_not_answer_is_inconclusive(data: dict[str, Any]) -> None:
    unit = _unit(criterion={"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}})
    verdict = evaluate(unit, {"ok": True, "data": data})
    assert (verdict.result, verdict.via) == ("inconclusive", "missing_field")


def test_a_mapping_keyed_by_position_also_answers() -> None:
    unit = _unit(criterion={"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}})
    verdict = evaluate(unit, {"ok": True, "data": {"rows": {"0": {"ssl": "on"}}}})
    assert verdict.result == "compliant"


@pytest.mark.parametrize(
    ("observed", "expected"),
    [("on", 1), (1, "on"), (True, 1), (1, True), (None, 1)],
)
def test_comparing_different_kinds_of_value_never_raises(observed: Any, expected: Any) -> None:
    unit = _unit(criterion={"threshold": {"field": "v", "operator": ">=", "value": expected}})
    verdict = evaluate(unit, {"ok": True, "data": {"v": observed}})
    assert (verdict.result, verdict.via) == ("inconclusive", "type_mismatch")


def test_booleans_are_compared_between_themselves() -> None:
    unit = _unit(criterion={"threshold": {"field": "v", "operator": "==", "value": True}})
    assert evaluate(unit, {"ok": True, "data": {"v": True}}).result == "compliant"
    assert evaluate(unit, {"ok": True, "data": {"v": False}}).result == "non_compliant"


@pytest.mark.parametrize("decision", [None, {}, {"compliant": "yes"}, {"compliant": 1}])
def test_an_opa_decision_without_a_boolean_is_inconclusive(decision: Any) -> None:
    unit = _unit(criterion={"opa": {"package": "argos.retention"}})
    verdict = evaluate(unit, {"ok": True, "data": {"count": 0}}, decision)
    assert (verdict.result, verdict.via) == ("inconclusive", "opa_invalid")


def test_a_failed_probe_never_becomes_a_finding() -> None:
    verdict = evaluate(UNIT, {"ok": False, "data": {"error": "connection refused"}})
    assert (verdict.result, verdict.via) == ("inconclusive", "probe_error")
    assert verdict.detail == {"error": "connection refused"}


def test_the_sample_that_cannot_absolve_says_how_much_would_be_needed() -> None:
    unit = _unit(
        criterion={"threshold": {"field": "count", "operator": "<=", "value": 200}},
        sampling={"population": 100_000, "sample": 383, "confidence": "0.95"},
    )
    verdict = evaluate(unit, {"ok": True, "data": {"count": 0}})
    assert verdict.result == "not_demonstrated"
    required = verdict.detail["sampling"]["required_sample"]
    assert 383 < required <= 100_000


def test_the_verdict_is_hashable_canonical_and_stable() -> None:
    first = evaluate(UNIT, {"ok": True, "data": {"count": 3}})
    second = evaluate(UNIT, {"ok": True, "data": {"count": 3}})
    assert first.canonical() == second.canonical()
    assert first.hash == second.hash and len(first.hash) == 64
    assert first.result in RESULTS
