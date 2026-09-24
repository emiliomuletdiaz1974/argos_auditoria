"""The security log: who tried what, apart from the functional journal (F09-08, ADR-0014).

`log(dsn).record(kind, actor, outcome, detail, source=...)` appends an event to `security.events`
(migration 0036), a chain of its own built with the algorithm of the journal v1 (ADR-0002) and
another genesis; `verify_chain(dsn)` checks it with the verifier of the journal, not a copy.

What goes in `detail` are identifiers and reasons, never contents: short scalars only (strings of
up to 200 characters, integers, booleans); anything else is refused.

A burst from one origin cannot fill the database: in each window of `WINDOW` seconds the first
`PER_WINDOW` events of a (kind, outcome, origin) are written one by one; the rest are counted and
become one summary event (`detail.suppressed`) when the window ends or on `flush()`.
"""

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg

from .journal import (
    Anomaly,
    JournalEntry,
    VerificationResult,
    canonicalize,
    verify_entries,
)

logger = logging.getLogger(__name__)

GENESIS = hashlib.sha256(b"ARGOS-SECURITY-GENESIS").digest()
PER_WINDOW = 10
WINDOW = 60.0
MAX_TEXT = 200
OUTCOMES = frozenset({"refused", "allowed", "failed", "succeeded"})


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    kind: str
    actor: str
    outcome: str
    detail: dict[str, Any]
    source: str

    def payload_canon(self) -> str:
        return canonicalize({"detail": self.detail, "outcome": self.outcome, "source": self.source})


def _checked_detail(detail: dict[str, Any]) -> dict[str, Any]:
    for key, value in detail.items():
        short = isinstance(value, str) and len(value) <= MAX_TEXT
        if not (short or value is None or isinstance(value, bool | int)):
            raise ValueError(
                f"security detail {key!r} must be a short scalar: identifiers and reasons only"
            )
    return dict(detail)


@dataclass
class _Window:
    started: float
    written: int = 0
    suppressed: int = 0
    last: SecurityEvent | None = None


@dataclass
class Recorder:
    """Folds bursts and hands the events to a sink (the database, or a list in the tests)."""

    sink: Callable[[SecurityEvent], None]
    clock: Callable[[], float] = time.monotonic
    per_window: int = PER_WINDOW
    window: float = WINDOW
    _windows: dict[tuple[str, str, str], _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        kind: str,
        actor: str,
        outcome: str,
        detail: dict[str, Any],
        source: str,
        origin: str | None = None,
    ) -> bool:
        """True if the event was written now; False if it was folded into a summary."""
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome: {outcome}")
        event = SecurityEvent(kind, actor, outcome, _checked_detail(detail), source)
        key = (kind, outcome, origin or actor)
        now = self.clock()
        pending: list[SecurityEvent] = []
        with self._lock:
            current = self._windows.get(key)
            if current is not None and now - current.started >= self.window:
                pending.extend(self._summary(current))
                current = None
            if current is None:
                current = self._windows[key] = _Window(started=now)
            write = current.written < self.per_window
            if write:
                current.written += 1
            else:
                current.suppressed += 1
                current.last = event
        for summary in pending:
            self.sink(summary)
        if write:
            self.sink(event)
        return write

    def _summary(self, window: _Window) -> list[SecurityEvent]:
        if not window.suppressed or window.last is None:
            return []
        last = window.last
        detail = {
            **last.detail,
            "suppressed": window.suppressed,
            "window_seconds": int(self.window),
        }
        window.suppressed = 0
        return [SecurityEvent(last.kind, last.actor, last.outcome, detail, last.source)]

    def flush(self) -> None:
        """Write the summaries still pending (on shutdown, and in the tests)."""
        with self._lock:
            pending = [s for w in self._windows.values() for s in self._summary(w)]
        for summary in pending:
            self.sink(summary)


def postgres_sink(dsn: str) -> Callable[[SecurityEvent], None]:
    def append(event: SecurityEvent) -> None:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "SELECT security.append(%s, %s, %s)",
                (event.actor, event.kind, event.payload_canon()),
            )

    return append


_recorders: dict[str, Recorder] = {}
_recorders_lock = threading.Lock()
_default: Recorder | None = None


def log(dsn: str) -> Recorder:
    """The recorder of a database, one per process, so the folding of bursts is shared."""
    with _recorders_lock:
        if dsn not in _recorders:
            _recorders[dsn] = Recorder(postgres_sink(dsn))
        return _recorders[dsn]


def configure(dsn: str) -> Recorder:
    """The recorder that `record()` uses, for code that does not know the database."""
    global _default
    _default = log(dsn)
    return _default


def reset() -> None:
    global _default
    _default = None
    with _recorders_lock:
        _recorders.clear()


def record(
    kind: str,
    actor: str,
    outcome: str,
    detail: dict[str, Any],
    source: str = "argos",
    origin: str | None = None,
) -> None:
    """Record with the configured recorder; without one, the event goes to the log, not nowhere."""
    if _default is None:
        logger.warning(
            "security event not recorded: no security log configured",
            extra={"kind": kind, "outcome": outcome},
        )
        return
    try:
        _default.record(kind, actor, outcome, detail, source, origin)
    except (psycopg.Error, OSError):
        logger.exception("security event not recorded", extra={"kind": kind, "outcome": outcome})


def _entries(dsn: str, mismatches: list[Anomaly]) -> Iterator[JournalEntry]:
    with psycopg.connect(dsn) as conn, conn.cursor(name="security_read") as cur:
        cur.itersize = 5000
        cur.execute(
            "SELECT seq, at_canon, actor, kind, payload_canon, prev_hash, entry_hash,"
            " source, outcome, detail FROM security.events ORDER BY seq"
        )
        for seq, at_canon, actor, kind, payload, prev, entry, source, outcome, detail in cur:
            # The columns people query are copies of what the hash covers: they must agree.
            shown = canonicalize({"detail": detail, "outcome": outcome, "source": source})
            if shown != payload:
                mismatches.append(Anomaly(seq, "columns do not match the hashed payload"))
            yield JournalEntry(seq, at_canon, actor, kind, payload, bytes(prev), bytes(entry))


def verify_chain(dsn: str) -> VerificationResult:
    """The whole chain, with the verifier of the journal v1 and the genesis of this log."""
    mismatches: list[Anomaly] = []
    result = verify_entries(_entries(dsn, mismatches), from_seq=1, prev_hash=GENESIS)
    if not mismatches:
        return result
    anomalies = tuple(sorted((*result.anomalies, *mismatches), key=lambda a: a.seq))
    return VerificationResult(result.verified, result.head_seq, result.head_hash, anomalies)
