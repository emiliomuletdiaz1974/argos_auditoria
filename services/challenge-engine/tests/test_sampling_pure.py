"""ARG-045 · the sampling module beyond the hand-calculated vectors."""

import pytest

from argos_challenges.sampling import (
    POPULATION_THRESHOLD,
    SamplingPlan,
    plan_sampling,
    required_sample_size,
    sample_size,
    wilson_upper,
)

UNIT = {"unit_id": "u-1", "sampling": {"confidence": 0.95, "margin": 0.05}}


def test_a_population_below_the_threshold_is_a_census() -> None:
    unit, plan = plan_sampling(UNIT, POPULATION_THRESHOLD)
    assert plan == SamplingPlan("census", POPULATION_THRESHOLD, POPULATION_THRESHOLD, 0.95, 0.05)
    assert unit["sampling"] is None


def test_a_large_population_is_sampled_with_the_declared_confidence() -> None:
    _, plan = plan_sampling(UNIT, 10_000)
    assert (plan.mode, plan.sample) == ("sample", sample_size(10_000))
    assert plan.as_dict()["confidence"] == "0.95"


def test_planning_never_changes_the_unit_it_receives() -> None:
    original = {"unit_id": "u-1", "sampling": {"confidence": 0.99, "margin": 0.02}}
    copy = {"unit_id": "u-1", "sampling": {"confidence": 0.99, "margin": 0.02}}
    planned, plan = plan_sampling(original, 50_000)
    assert original == copy
    assert planned is not original and plan.confidence == 0.99


def test_the_bound_falls_as_the_sample_grows_and_rises_with_failures() -> None:
    assert wilson_upper(0, 1000) < wilson_upper(0, 100)
    assert wilson_upper(5, 100) > wilson_upper(1, 100)
    assert wilson_upper(0, 100, 0.99) > wilson_upper(0, 100, 0.90)


def test_the_required_sample_is_the_smallest_one_that_demonstrates_it() -> None:
    for failures, target in ((0, 0.01), (1, 0.05), (3, 0.10)):
        size = required_sample_size(failures, target)
        assert wilson_upper(failures, size) < target
        assert wilson_upper(failures, size - 1) >= target


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: sample_size(0), "population"),
        (lambda: sample_size(100, margin=0.0), "margin"),
        (lambda: sample_size(100, confidence=0.5), "confidence"),
        (lambda: wilson_upper(-1, 10), "negative"),
        (lambda: wilson_upper(11, 10), "more failures"),
        (lambda: required_sample_size(0, 0.0), "target"),
        (lambda: required_sample_size(0, 1.0), "target"),
    ],
)
def test_impossible_arguments_are_rejected(call, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=message):
        call()
