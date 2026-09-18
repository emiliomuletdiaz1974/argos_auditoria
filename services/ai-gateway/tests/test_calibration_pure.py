"""ARG-055 · a confidence that means what it says (F06-08).

A model says 0.9 and is right 0.7 of the time. The thresholds of ARG-025 (accept at 0.85, review
from 0.50) would be arbitrary without correcting that, so the declared confidence goes through an
isotonic curve fitted on the DPO's own decisions before it reaches the triage.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest
from argos_ai.classify.calibration import (
    MINIMUM_PAIRS,
    UNTRUSTED_CEILING,
    Calibrator,
    Decision,
    isotonic_blocks,
    precision_by_category,
)


def test_the_pool_adjacent_violators_give_the_curve_worked_out_by_hand() -> None:
    """(0.2 → right, 0.3 → wrong) violate the order and are pooled into 0.5."""
    pairs = [(0.1, 0), (0.2, 1), (0.3, 0), (0.4, 1), (0.9, 1), (0.95, 1)]
    assert isotonic_blocks(pairs) == [(0.1, 0.0), (0.2, 0.5), (0.4, 1.0)]


def test_the_curve_never_goes_down() -> None:
    rng = random.Random(7)  # noqa: S311 - reproducible test data, not cryptography
    pairs = [(rng.random(), rng.randint(0, 1)) for _ in range(300)]
    values = [value for _, value in isotonic_blocks(pairs)]
    assert values == sorted(values)


def _decisions(category: str, count: int, declared: float, right_every: int) -> list[Decision]:
    """`count` decisions at one declared confidence, right once every `right_every`."""
    return [
        Decision(category, declared, index % right_every == 0, datetime(2026, 9, 1, tzinfo=UTC))
        for index in range(count)
    ]


def test_an_overconfident_model_is_brought_down_to_its_real_hit_rate() -> None:
    """Declared 0.9, right one time in two: the triage must see 0.5, not 0.9."""
    calibrator = Calibrator.fit(_decisions("personal_data", 60, 0.9, right_every=2))
    assert calibrator.calibrate("personal_data", 0.9) == pytest.approx(0.5)


def test_below_the_minimum_the_curve_is_the_identity_with_a_conservative_ceiling() -> None:
    """Forty-nine labels are not enough to trust a curve, nor to trust the model's 0.95."""
    calibrator = Calibrator.fit(_decisions("personal_data", MINIMUM_PAIRS - 1, 0.9, 1))
    assert calibrator.calibrate("personal_data", 0.95) == UNTRUSTED_CEILING
    assert calibrator.calibrate("personal_data", 0.60) == pytest.approx(0.60)


def test_with_the_ceiling_nothing_is_accepted_without_a_human() -> None:
    """0.8 is below the 0.85 acceptance of ARG-025: an uncalibrated model can only queue."""
    assert UNTRUSTED_CEILING < 0.85


def test_each_category_has_its_own_curve() -> None:
    """Being good at identifiers says nothing about being good at health data."""
    decisions = _decisions("official_identifier", 60, 0.9, right_every=1)
    decisions += _decisions("special_category.health", 60, 0.9, right_every=3)
    calibrator = Calibrator.fit(decisions)
    assert calibrator.calibrate("official_identifier", 0.9) == pytest.approx(1.0)
    assert calibrator.calibrate("special_category.health", 0.9) == pytest.approx(1 / 3, abs=0.01)


def test_a_category_without_decisions_falls_back_to_the_ceiling() -> None:
    calibrator = Calibrator.fit(_decisions("personal_data", 60, 0.9, right_every=1))
    assert calibrator.calibrate("financial_data", 0.99) == UNTRUSTED_CEILING


def test_a_declared_value_between_blocks_takes_the_block_it_falls_in() -> None:
    decisions = _decisions("personal_data", 30, 0.3, right_every=5)
    decisions += _decisions("personal_data", 30, 0.9, right_every=1)
    calibrator = Calibrator.fit(decisions)
    assert calibrator.calibrate("personal_data", 0.5) == pytest.approx(0.2)
    assert calibrator.calibrate("personal_data", 0.1) == pytest.approx(0.2)
    assert calibrator.calibrate("personal_data", 0.95) == pytest.approx(1.0)


def test_the_curve_can_be_saved_and_read_back_identical() -> None:
    calibrator = Calibrator.fit(_decisions("personal_data", 60, 0.9, right_every=2))
    again = Calibrator.from_curves(calibrator.curves())
    assert again.calibrate("personal_data", 0.9) == calibrator.calibrate("personal_data", 0.9)


def test_the_drift_is_the_precision_of_the_last_thirty_days_per_category() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    recent = [
        Decision("personal_data", 0.9, right, now - timedelta(days=3))
        for right in (True, True, True, False)
    ]
    old = [Decision("personal_data", 0.9, False, now - timedelta(days=45)) for _ in range(10)]
    assert precision_by_category([*recent, *old], now=now) == {"personal_data": 0.75}


def test_equal_declared_confidences_are_one_point_not_a_rising_curve() -> None:
    """Misses and hits at the same 0.9 must average; sorted raw they would look like 0 → 1."""
    pairs = [(0.9, 0), (0.9, 1), (0.9, 0), (0.9, 1)]
    assert isotonic_blocks(pairs) == [(0.9, 0.5)]
