"""Load budget: rate, agreed windows, rows per probe and latency circuit breaker (ARG-013, P-05).

`LoadBudget` holds the rules; its state lives in a store. In memory (the default) it is one
process's; in PostgreSQL (`budget_pg.PostgresBudgetStore`) it is the system's, shared by every
process that probes it, which is what P-05 asks for (security review F09-02, SEC-004).
"""

import statistics
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as clock_time
from typing import Any, Protocol
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


LATENCY_WINDOW = 20


@dataclass
class BudgetState:
    """What a budget remembers. Times are seconds on the store's clock; `now` is read under lock."""

    tokens: float
    now: float
    last: float
    circuit: str = "closed"
    opened_at: float | None = None
    trial_at: float | None = None
    latencies: list[int] = field(default_factory=list)


class BudgetStore(Protocol):
    def locked(self, burst: float) -> AbstractContextManager[BudgetState]: ...


class InMemoryBudgetStore:
    """The state of one process, behind a thread lock."""

    def __init__(self, burst: float, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BudgetState(tokens=burst, now=clock(), last=clock())

    @contextmanager
    def locked(self, burst: float) -> Iterator[BudgetState]:
        with self._lock:
            self._state.now = self._clock()
            yield self._state


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
        store: BudgetStore | None = None,
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
        self._store: BudgetStore = store or InMemoryBudgetStore(self._burst, monotonic)

    @property
    def state(self) -> str:
        with self._store.locked(self._burst) as st:
            return st.circuit

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
        with self._store.locked(self._burst) as st:
            if st.circuit == "open":
                if st.opened_at is not None and st.now - st.opened_at < self._cooldown:
                    raise CircuitOpenError("circuit open: the system is responding slowly", details)
                st.circuit, st.trial_at = "half_open", None
            if st.circuit == "half_open":
                # A trial handed out and never reported (its process died) expires with the
                # cooldown: the system is not left locked for ever.
                if st.trial_at is not None and st.now - st.trial_at < self._cooldown:
                    raise CircuitOpenError("circuit half-open: a trial probe is in flight", details)
                st.trial_at = st.now
        deadline = self._monotonic() + self._max_wait
        while True:
            with self._store.locked(self._burst) as st:
                st.tokens = min(self._burst, st.tokens + max(0.0, st.now - st.last) * self._rate)
                st.last = st.now
                if st.tokens >= 1.0:
                    st.tokens -= 1.0
                    return
            if self._monotonic() >= deadline:
                with self._store.locked(self._burst) as st:
                    if st.circuit == "half_open":
                        st.trial_at = None
                raise BudgetExceededError("rate budget exhausted (maximum wait reached)", details)
            self._sleep(0.25)

    # ---------- circuit breaker ----------
    def observe_latency(self, ms: int) -> None:
        opened_with: float | None = None
        with self._store.locked(self._burst) as st:
            if st.circuit == "half_open":
                st.trial_at = None
                if ms <= self._limit_ms:
                    st.circuit, st.latencies = "closed", []
                else:
                    opened_with = float(ms)
                    self._open(st)
            elif st.circuit == "closed":
                st.latencies = [*st.latencies, ms][-LATENCY_WINDOW:]
                if len(st.latencies) >= 5:
                    p50 = float(statistics.median(st.latencies))
                    if p50 > self._limit_ms:
                        opened_with = p50
                        self._open(st)
        if opened_with is not None and self._on_open is not None:
            try:
                self._on_open(self.system_id, opened_with)
            except Exception:
                _log.exception("circuit listener failed", extra={"trace_id": self.system_id})

    @staticmethod
    def _open(st: BudgetState) -> None:
        st.circuit, st.opened_at, st.latencies = "open", st.now, []
