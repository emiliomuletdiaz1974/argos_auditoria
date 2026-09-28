"""ARG-095 · assisted failover of the size M, on a pair of its own (F10-09, ADR-0015 point 8).

The profile `ha` of the compose starts two PostgreSQL of the image of ARGOS, `ha-node-a` primary
and `ha-node-b` its physical replica with a slot. They are not the database of the development
environment: stopping the primary here stops nothing else. The test walks the runbook RB-07:

- the drill changes nothing;
- with the primary alive, the failover aborts: two primaries would be two truths;
- with the primary stopped, the replica is promoted, the journal verifies on it and the failover
  is recorded in the journal;
- the old primary comes back as a replica of the new one, never as a primary.
"""

import importlib.util
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import psycopg
import pytest

from argos_common.journal_pg import PostgresJournal
from argos_common.migrations import apply_migrations

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
HA = REPO / "platform" / "ha" / "size-m"
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(REPO / "deploy" / "dev" / "compose.yaml"),
    "--profile",
    "ha",
]
NODE_A = "postgresql://argos:dev-only-ha@127.0.0.1:55441/argos?connect_timeout=3"
NODE_B = "postgresql://argos:dev-only-ha@127.0.0.1:55442/argos?connect_timeout=3"
MIGRATIONS = REPO / "services" / "api" / "migrations"


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HA / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _compose(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(  # noqa: S603 - fixed commands against the development environment
        [*COMPOSE, *args], check=True, capture_output=True, timeout=600,
        env={**os.environ, **(env or {})},
    )  # fmt: skip


def _in_recovery(dsn: str) -> bool | None:
    try:
        with psycopg.connect(dsn) as conn:
            row = conn.execute("SELECT pg_is_in_recovery()").fetchone()
    except psycopg.OperationalError:
        return None
    return bool(row[0]) if row else None


def _wait(condition, seconds: float = 180) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(2)
    raise AssertionError("the condition did not hold in time")


@pytest.fixture(scope="module")
def pair() -> Iterator[None]:
    _compose("rm", "-sfv", "ha-node-a", "ha-node-b")
    volumes = ["argos-dev_ha-a-data", "argos-dev_ha-b-data"]
    subprocess.run(  # noqa: S603 - fixed command against the development environment
        ["docker", "volume", "rm", "-f", *volumes],  # noqa: S607
        capture_output=True,
        timeout=60,  # noqa: S607
    )
    _compose("up", "-d", "ha-node-a")
    _wait(lambda: _in_recovery(NODE_A) is False)
    apply_migrations(NODE_A, MIGRATIONS)
    journal = PostgresJournal(NODE_A)
    for n in range(5):
        journal.append("user:tester", "test.ha", {"n": n})
    _compose("up", "-d", "ha-node-b")
    _wait(lambda: _in_recovery(NODE_B) is True)
    head, _ = journal.head()
    _wait(lambda: PostgresJournal(NODE_B).head()[0] == head)
    yield
    _compose("rm", "-sfv", "ha-node-a", "ha-node-b")


def test_the_drill_changes_nothing(pair: None) -> None:
    failover = _script("failover")
    assert failover.main(["--primary-dsn", NODE_A, "--replica-dsn", NODE_B]) == 1  # primary alive
    _compose("stop", "ha-node-a")
    try:
        assert failover.main(["--primary-dsn", NODE_A, "--replica-dsn", NODE_B]) == 0
        assert _in_recovery(NODE_B) is True, "a drill must not promote"
    finally:
        _compose("start", "ha-node-a")
        _wait(lambda: _in_recovery(NODE_A) is False)


def test_with_the_primary_alive_the_failover_aborts(pair: None) -> None:
    failover = _script("failover")
    code = failover.main(["--primary-dsn", NODE_A, "--replica-dsn", NODE_B, "--confirm"])
    assert code == 1
    assert _in_recovery(NODE_B) is True


def test_with_the_primary_down_the_replica_is_promoted_and_the_old_one_rejoins(pair: None) -> None:
    failover, rejoin = _script("failover"), _script("rejoin")
    _compose("stop", "ha-node-a")
    code = failover.main(["--primary-dsn", NODE_A, "--replica-dsn", NODE_B, "--confirm"])
    assert code == 0
    assert _in_recovery(NODE_B) is False
    promoted = PostgresJournal(NODE_B)
    assert promoted.verify().intact
    last_seq, _ = promoted.head()
    [entry] = list(promoted.read(last_seq, last_seq))
    assert entry.action == "ha.failover"
    # The old primary comes back as a replica of the new one.
    code = rejoin.main(
        ["--node", "ha-node-a", "--node-dsn", NODE_A, "--primary", "ha-node-b",
         "--primary-dsn", NODE_B, "--compose-file", str(REPO / "deploy" / "dev" / "compose.yaml"),
         "--confirm"]
    )  # fmt: skip
    assert code == 0
    assert _in_recovery(NODE_A) is True
    promoted.append("user:tester", "test.ha", {"after": "rejoin"})
    head, _ = promoted.head()
    _wait(lambda: PostgresJournal(NODE_A).head()[0] == head)
