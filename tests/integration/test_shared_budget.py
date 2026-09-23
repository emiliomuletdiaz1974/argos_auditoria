"""SEC-004 · the load budget of a system is one, whoever asks (campaign, rescan or classification).

Two `LoadBudget` over the same PostgreSQL row behave as two processes would: they share tokens,
the circuit one opens is open for the other, and a trial probe whose process died does not keep
the system locked.
"""

import time
from typing import Any

import psycopg
import pytest

from argos_common.ids import uuid7
from argos_connector.budget import LoadBudget
from argos_connector.budget_pg import PostgresBudgetStore
from argos_connector.errors import BudgetExceededError, CircuitOpenError

pytestmark = pytest.mark.integration


def _pair(dsn: str, **config: Any) -> tuple[LoadBudget, LoadBudget, str]:
    system_id = str(uuid7())
    one = LoadBudget(system_id, config, store=PostgresBudgetStore(dsn, system_id))
    other = LoadBudget(system_id, config, store=PostgresBudgetStore(dsn, system_id))
    return one, other, system_id


def test_two_processes_share_the_tokens_of_a_system(migrated_db: str) -> None:
    one, other, _ = _pair(migrated_db, queries_per_minute=1, burst=2, max_wait_s=0.5)
    one.acquire()
    other.acquire()
    with pytest.raises(BudgetExceededError, match="rate"):
        one.acquire()
    with pytest.raises(BudgetExceededError, match="rate"):
        other.acquire()


def test_other_systems_keep_their_own_budget(migrated_db: str) -> None:
    one, _, _ = _pair(migrated_db, queries_per_minute=1, burst=1, max_wait_s=0.5)
    third, _, _ = _pair(migrated_db, queries_per_minute=1, burst=1, max_wait_s=0.5)
    one.acquire()
    third.acquire()


def test_a_circuit_opened_by_one_process_is_open_for_the_other(migrated_db: str) -> None:
    events: list[tuple[str, float]] = []
    system_id = str(uuid7())
    config = {"latency_p50_limit_ms": 10, "open_cooldown_s": 300}
    one = LoadBudget(
        system_id,
        config,
        store=PostgresBudgetStore(migrated_db, system_id),
        on_circuit_open=lambda s, p: events.append((s, p)),
    )
    other = LoadBudget(system_id, config, store=PostgresBudgetStore(migrated_db, system_id))
    for _ in range(5):
        one.observe_latency(500)
    assert events == [(system_id, 500.0)]
    with pytest.raises(CircuitOpenError):
        other.acquire()


def test_a_trial_whose_process_died_does_not_lock_the_system(migrated_db: str) -> None:
    system_id = str(uuid7())
    config = {"latency_p50_limit_ms": 10, "open_cooldown_s": 1}
    dead = LoadBudget(system_id, config, store=PostgresBudgetStore(migrated_db, system_id))
    for _ in range(5):
        dead.observe_latency(500)
    time.sleep(1.2)
    dead.acquire()  # the trial probe; its process dies before reporting a latency
    survivor = LoadBudget(system_id, config, store=PostgresBudgetStore(migrated_db, system_id))
    with pytest.raises(CircuitOpenError, match="trial"):
        survivor.acquire()
    time.sleep(1.2)
    survivor.acquire()  # the abandoned trial expired with the cooldown


def test_the_row_is_the_only_state(migrated_db: str) -> None:
    one, _, system_id = _pair(migrated_db, queries_per_minute=60, burst=3)
    one.acquire()
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT tokens, state FROM argos.load_budget WHERE system_id = %s", (system_id,)
        ).fetchone()
    assert row is not None
    assert 1.9 <= float(row[0]) <= 2.1 and row[1] == "closed"
