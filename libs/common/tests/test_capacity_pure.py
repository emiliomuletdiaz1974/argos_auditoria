"""ARG-098 · the limits of each size, and the honest refusal (F10-08)."""

from pathlib import Path

import pytest

from argos_common.capacity import (
    DIMENSIONS,
    CapacityExceededError,
    band,
    check,
    limits_of,
    load_sizes,
)

SIZES = Path(__file__).resolve().parents[3] / "platform" / "operation" / "sizes.yaml"


@pytest.mark.parametrize(
    ("used", "expected"), [(0, "green"), (79, "green"), (80, "amber"), (99, "amber"), (100, "red")]
)
def test_the_bands_turn_at_80_and_100_percent(used: int, expected: str) -> None:
    assert band(used, 100) == expected


def test_the_three_sizes_declare_every_dimension() -> None:
    sizes = load_sizes(SIZES)
    assert set(sizes) == {"S", "M", "L"}
    for limits in sizes.values():
        assert set(limits) == set(DIMENSIONS)
    assert sizes["S"]["systems"] == 40


def test_the_41st_system_of_an_s_is_refused_with_the_options() -> None:
    limits = load_sizes(SIZES)["S"]
    check(limits, "systems", used=39)  # the 40th fits
    with pytest.raises(CapacityExceededError) as refused:
        check(limits, "systems", used=40)
    message = str(refused.value)
    assert "40" in message
    # The refusal says what can be done, not only that it cannot.
    for option in ("reducir", "ampliar", "informe de capacidad"):
        assert option in message.lower()
    assert refused.value.details == {"dimension": "systems", "used": 40, "limit": 40, "size": "S"}


def test_an_unknown_size_is_refused_at_start() -> None:
    with pytest.raises(ValueError, match="XL"):
        limits_of(SIZES, "XL")
