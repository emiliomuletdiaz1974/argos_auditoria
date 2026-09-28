"""QA-26 · the inventory at its edges, without a database.

- QA-029: deltas wait while the ingest consumer still has messages of the run in flight; grants of
  a table not yet ingested are delivered again instead of vanishing.
- QA-043: a validation probe that could not run leaves its columns marked for the next pass.
- QA-040: a snapshot whose nodes no longer give its hash is refused before a campaign uses it.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from temporalio.exceptions import ApplicationError

from argos_connector.probes import ProbeSpec
from argos_inventory.classify import deterministic
from argos_inventory.ingest.handlers import SystemMeta, ingest_access_found
from argos_inventory.scheduler.activities import INGESTION_PENDING, InventoryActivities

SID = "0190f000-0000-7000-8000-000000000001"


class FakeStore:
    def __init__(self, answers: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.answers = answers or {}
        self.executed: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def connection(self) -> Iterator[None]:
        yield None

    def query(self, cypher: str, params: Any = None, columns: Any = (), conn: Any = None) -> Any:
        for fragment, rows in self.answers.items():
            if fragment in cypher:
                return rows
        return []

    def execute(self, cypher: str, params: Any = None, conn: Any = None) -> None:
        self.executed.append((cypher, dict(params or {})))


def test_deltas_wait_while_the_ingest_consumer_has_messages_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def backlog() -> int:
        return 3

    activities = InventoryActivities.__new__(InventoryActivities)
    activities._ingestion_backlog = backlog
    monkeypatch.setattr(activities, "_last_ingested", lambda system_id: "run-1", raising=False)
    with pytest.raises(ApplicationError) as waiting:
        asyncio.run(activities.compute_run_deltas(SID, "run-1"))
    assert waiting.value.type == INGESTION_PENDING


def test_grants_of_a_table_not_yet_ingested_are_delivered_again() -> None:
    store = FakeStore()
    data = {
        "system_id": SID, "schema": "public", "table": "patients",
        "observed_at": "2026-09-28T00:00:00+00:00",
        "source_connector": "sql", "probe_id": "p", "journal_seq": 1, "run_id": "run-1",
        "grants": [{"grantee": "app", "privilege": "SELECT"}],
    }  # fmt: skip
    meta = SystemMeta(SID, "db", "rdbms", "owner")
    with pytest.raises(LookupError):
        ingest_access_found(store, "discovery.access_found.v1", data, meta)  # type: ignore[arg-type]
    assert store.executed == [], "nothing written: the event comes back later"


def test_a_validation_that_could_not_run_is_marked_for_the_next_pass() -> None:
    store = FakeStore({"NOT exists((c)-[:CLASSIFIED_AS]->())": [
        {"key": "k1", "name": "dni", "table": "public.patients"},
    ]})  # fmt: skip

    def runner(system_id: str, spec: ProbeSpec) -> Any:
        raise ValueError("outside the agreed probe window")

    deterministic.classify_new_columns(store, runner, SID)  # type: ignore[arg-type]
    marks = [p for cypher, p in store.executed if "validation_pending" in cypher]
    assert marks and marks[-1]["pending"] is True and marks[-1]["keys"] == ["k1"]


def test_a_snapshot_that_no_longer_gives_its_hash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from argos_challenges import snapshot_resolver

    monkeypatch.setattr(snapshot_resolver, "verify_snapshot", lambda dsn, sid: False, raising=False)
    monkeypatch.setattr(snapshot_resolver, "snapshot_nodes", lambda dsn, sid: [])
    with pytest.raises(snapshot_resolver.SnapshotAlteredError):
        snapshot_resolver.SnapshotSelectorResolver("postgresql://unused", "snap-1")
