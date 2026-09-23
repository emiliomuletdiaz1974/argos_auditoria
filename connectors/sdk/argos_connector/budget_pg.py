"""The state of a load budget kept in PostgreSQL, one row per system (ARG-013, SEC-004).

`LoadBudget` holds the rules (tokens, windows, circuit breaker); a store holds the state. With this
store every process that probes a system reads and writes the same row under a row lock, so a
campaign, a rescan and a classification share one budget. The clock is the database's.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .budget import BudgetState

_ENSURE = (
    "INSERT INTO argos.load_budget (system_id, tokens) VALUES (%s, %s) "
    "ON CONFLICT (system_id) DO NOTHING"
)
_READ = (
    "SELECT tokens, extract(epoch FROM clock_timestamp())::float8, "
    "extract(epoch FROM updated_at)::float8, state, extract(epoch FROM opened_at)::float8, "
    "extract(epoch FROM trial_at)::float8, latencies "
    "FROM argos.load_budget WHERE system_id = %s FOR UPDATE"
)
_WRITE = (
    "UPDATE argos.load_budget SET tokens = %s, updated_at = to_timestamp(%s), state = %s, "
    "opened_at = to_timestamp(%s), trial_at = to_timestamp(%s), latencies = %s "
    "WHERE system_id = %s"
)


class PostgresBudgetStore:
    def __init__(self, dsn: str, system_id: str) -> None:
        self._dsn = dsn
        self._system_id = system_id

    @contextmanager
    def locked(self, burst: float) -> Iterator[BudgetState]:
        """The row of the system, locked until the block ends and written back if it succeeds."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_ENSURE, (self._system_id, burst))
            row: Any = conn.execute(_READ, (self._system_id,)).fetchone()
            state = BudgetState(
                tokens=float(row[0]),
                now=float(row[1]),
                last=float(row[2]),
                circuit=str(row[3]),
                opened_at=row[4],
                trial_at=row[5],
                latencies=list(row[6]),
            )
            yield state
            conn.execute(
                _WRITE,
                (
                    state.tokens,
                    state.last,
                    state.circuit,
                    state.opened_at,
                    state.trial_at,
                    state.latencies,
                    self._system_id,
                ),
            )
