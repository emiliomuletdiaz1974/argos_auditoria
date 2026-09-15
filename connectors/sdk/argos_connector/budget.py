"""Load budget: rate, agreed windows, rows per probe and latency circuit breaker (ARG-013, P-05)."""

import collections
import statistics
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

from argos_common.logs import get_logger

from .errors import BudgetExceededError, CircuitOpenError

CircuitListener = Callable[[str, float], None]

DEFAULTS: dict[str, Any] = {
    "queries_per_minute": 30,
    "burst": 10,
    "windows": [{"days": "mon-sun", "from": "00:00", "to": "23:59"}],
    "latency_p50_limit_ms": 2000,  # when the rolling median exceeds this, open the circuit
    "open_cooldown_s": 300,
    "max_rows_per_probe": 10_000,
    "max_wait_s": 120.0,
    "tz": "Europe/Madrid",
}
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_log = get_logger(__name__, "ARG-013")


@dataclass(frozen=True, slots=True)
class Window:
    days: frozenset[int]
    start: clock_time
    end: clock_time


def _day(token: str) -> int:
    try:
        return DAYS[token]
    except KeyError:
        raise ValueError(f"unknown day {token!r} (use mon, tue, wed, thu, fri, sat, sun)") from None


def _days(spec: str) -> frozenset[int]:
    parts = spec.split("-")
    if len(parts) == 1:
        return frozenset({_day(parts[0])})
    if len(parts) != 2:
        raise ValueError(f"invalid day range {spec!r}")
    first, last = _day(parts[0]), _day(parts[1])
    if first <= last:
        return frozenset(range(first, last + 1))
    return frozenset([*range(first, 7), *range(0, last + 1)])


def _hhmm(value: str) -> clock_time:
    if len(value) != 5 or value[2] != ":":
        raise ValueError(f"invalid time {value!r} (use HH:MM)")
    return clock_time.fromisoformat(value)


def parse_windows(raw: object) -> tuple[Window, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("windows must be a non-empty list")
    return tuple(Window(_days(w["days"]), _hhmm(w["from"]), _hhmm(w["to"])) for w in raw)


class LoadBudget:
    def __init__(
        self,
        system_id: str,
        config: Mapping[str, Any] | None = None,
        *,
        on_circuit_open: CircuitListener | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        unknown = set(config or {}) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown budget settings: {sorted(unknown)}")
        cfg = {**DEFAULTS, **(config or {})}
        self.system_id = system_id
        self._tz = ZoneInfo(cfg["tz"])
        self._windows = parse_windows(cfg["windows"])
        self._rate = float(cfg["queries_per_minute"]) / 60.0
        self._burst = float(cfg["burst"])
        self._limit_ms = float(cfg["latency_p50_limit_ms"])
        self._cooldown = float(cfg["open_cooldown_s"])
        self._max_wait = float(cfg["max_wait_s"])
        self._max_rows = int(cfg["max_rows_per_probe"])
        if min(self._rate, self._burst, self._limit_ms, self._max_rows) <= 0:
            raise ValueError("budget limits must be positive")
        self._on_open = on_circuit_open
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(self._tz))
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = self._burst
        self._last = monotonic()
        self._latencies: collections.deque[int] = collections.deque(maxlen=20)
        self._state = "closed"
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        return self._state

    @property
    def max_rows_per_probe(self) -> int:
        return self._max_rows

    # ---------- windows ----------
    def in_window(self) -> bool:
        now = self._now().astimezone(self._tz)
        minute = now.time().replace(second=0, microsecond=0)
        return any(now.weekday() in w.days and w.start <= minute <= w.end for w in self._windows)

    # ---------- token bucket + circuit gate ----------
    def acquire(self) -> None:
        details = {"system_id": self.system_id}
        if not self.in_window():
            raise BudgetExceededError("outside the agreed probe window", details=details)
        with self._lock:
            if self._state == "open":
                if self._monotonic() - self._opened_at < self._cooldown:
                    raise CircuitOpenError("circuit open: the system is responding slowly", details)
                self._state, self._trial_in_flight = "half_open", False
            if self._state == "half_open":
                if self._trial_in_flight:
                    raise CircuitOpenError("circuit half-open: a trial probe is in flight", details)
                self._trial_in_flight = True
        deadline = self._monotonic() + self._max_wait
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            if self._monotonic() >= deadline:
                with self._lock:
                    self._trial_in_flight = False
                raise BudgetExceededError("rate budget exhausted (maximum wait reached)", details)
            self._sleep(0.25)

    def _refill(self) -> None:
        now = self._monotonic()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now

    # ---------- circuit breaker ----------
    def observe_latency(self, ms: int) -> None:
        opened_with: float | None = None
        with self._lock:
            if self._state == "half_open":
                self._trial_in_flight = False
                if ms <= self._limit_ms:
                    self._state = "closed"
                    self._latencies.clear()
                else:
                    opened_with = float(ms)
                    self._open()
            elif self._state == "closed":
                self._latencies.append(ms)
                if len(self._latencies) >= 5:
                    p50 = float(statistics.median(self._latencies))
                    if p50 > self._limit_ms:
                        opened_with = p50
                        self._open()
        if opened_with is not None and self._on_open is not None:
            try:
                self._on_open(self.system_id, opened_with)
            except Exception:
                _log.exception("circuit listener failed", extra={"trace_id": self.system_id})

    def _open(self) -> None:
        self._state = "open"
        self._opened_at = self._monotonic()
        self._latencies.clear()
