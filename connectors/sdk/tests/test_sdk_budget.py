"""Load budget (ARG-013): windows, token bucket, max rows and latency circuit breaker."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from argos_connector.budget import LoadBudget
from argos_connector.errors import BudgetExceededError, CircuitOpenError

MADRID = ZoneInfo("Europe/Madrid")
MONDAY_10 = datetime(2026, 9, 14, 10, 0, tzinfo=MADRID)  # 2026-09-14 is a Monday


class FakeClock:
    def __init__(self, start: datetime = MONDAY_10) -> None:
        self.mono = 1000.0
        self.wall = start
        self.slept = 0.0

    def monotonic(self) -> float:
        return self.mono

    def now(self) -> datetime:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def _budget(
    clock: FakeClock, events: list[tuple[str, float]] | None = None, **config: Any
) -> LoadBudget:
    return LoadBudget(
        "sys-1",
        config,
        on_circuit_open=(lambda s, p: events.append((s, p))) if events is not None else None,
        monotonic=clock.monotonic,
        now=clock.now,
        sleep=clock.sleep,
    )


def test_defaults_allow_a_probe() -> None:
    clock = FakeClock()
    budget = _budget(clock)
    budget.acquire()
    assert budget.state == "closed" and budget.max_rows_per_probe == 10_000


def test_unknown_config_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="queries_per_hour"):
        _budget(FakeClock(), queries_per_hour=5)


@pytest.mark.parametrize(
    "window",
    [
        {"days": "lun-dom", "from": "00:00", "to": "23:59"},
        {"days": "mon-tue-wed", "from": "00:00", "to": "23:59"},
        {"days": "mon-sun", "from": "9:00", "to": "23:59"},
        {"days": "mon-sun", "from": "25:00", "to": "23:59"},
    ],
)
def test_invalid_windows_are_rejected(window: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        _budget(FakeClock(), windows=[window])


def test_outside_the_window_the_probe_waits_for_another_day() -> None:
    budget = _budget(FakeClock(), windows=[{"days": "sat-sun", "from": "00:00", "to": "23:59"}])
    with pytest.raises(BudgetExceededError, match="window"):
        budget.acquire()


def test_window_wrapping_the_week() -> None:
    budget = _budget(FakeClock(), windows=[{"days": "fri-mon", "from": "09:00", "to": "18:00"}])
    assert budget.in_window()


def test_window_bounds_are_inclusive_to_the_minute() -> None:
    clock = FakeClock()
    budget = _budget(clock, windows=[{"days": "mon", "from": "10:00", "to": "10:00"}])
    assert budget.in_window()
    clock.advance(60)
    assert not budget.in_window()


def test_burst_then_wait_for_the_next_token() -> None:
    clock = FakeClock()
    budget = _budget(clock, queries_per_minute=60, burst=2, max_wait_s=5)
    budget.acquire()
    budget.acquire()
    assert clock.slept == 0
    budget.acquire()
    assert 0.9 <= clock.slept <= 1.25


def test_rate_budget_exhausted_after_max_wait() -> None:
    clock = FakeClock()
    budget = _budget(clock, queries_per_minute=1, burst=1, max_wait_s=1)
    budget.acquire()
    with pytest.raises(BudgetExceededError, match="rate"):
        budget.acquire()


def test_slow_median_opens_the_circuit_and_notifies_once() -> None:
    events: list[tuple[str, float]] = []
    budget = _budget(FakeClock(), events, latency_p50_limit_ms=2000)
    for _ in range(4):
        budget.observe_latency(3000)
    assert budget.state == "closed"
    budget.observe_latency(3000)
    assert budget.state == "open"
    assert events == [("sys-1", 3000.0)]


def test_fast_probes_keep_the_circuit_closed() -> None:
    budget = _budget(FakeClock(), latency_p50_limit_ms=2000)
    for ms in (3000, 3000, 100, 100, 100):
        budget.observe_latency(ms)
    assert budget.state == "closed"


def _open(clock: FakeClock, events: list[tuple[str, float]] | None = None) -> LoadBudget:
    budget = _budget(clock, events, latency_p50_limit_ms=2000, open_cooldown_s=300)
    for _ in range(5):
        budget.observe_latency(5000)
    assert budget.state == "open"
    return budget


def test_open_circuit_refuses_until_the_cooldown_ends() -> None:
    clock = FakeClock()
    budget = _open(clock)
    with pytest.raises(CircuitOpenError):
        budget.acquire()
    clock.advance(301)
    budget.acquire()
    assert budget.state == "half_open"
    with pytest.raises(CircuitOpenError, match="trial"):
        budget.acquire()


def test_fast_trial_closes_the_circuit_and_forgets_old_latencies() -> None:
    clock = FakeClock()
    budget = _open(clock)
    clock.advance(301)
    budget.acquire()
    budget.observe_latency(100)
    assert budget.state == "closed"
    for _ in range(4):
        budget.observe_latency(5000)
    assert budget.state == "closed"


def test_slow_trial_reopens_and_notifies_again() -> None:
    clock = FakeClock()
    events: list[tuple[str, float]] = []
    budget = _open(clock, events)
    clock.advance(301)
    budget.acquire()
    budget.observe_latency(4000)
    assert budget.state == "open"
    assert events == [("sys-1", 5000.0), ("sys-1", 4000.0)]


def test_a_failing_listener_does_not_break_the_probe() -> None:
    def boom(system_id: str, p50: float) -> None:
        raise RuntimeError("bus down")

    budget = LoadBudget("sys-1", {"latency_p50_limit_ms": 10}, on_circuit_open=boom)
    for _ in range(5):
        budget.observe_latency(50)
    assert budget.state == "open"


def test_max_rows_per_probe_is_configurable() -> None:
    assert _budget(FakeClock(), max_rows_per_probe=500).max_rows_per_probe == 500
