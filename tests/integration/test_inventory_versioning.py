"""ARG-023 · deltas between scan runs and immutable inventory snapshots."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from argos_inventory.graph.model import table_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor
from argos_inventory.versioning.deltas import compute_deltas, iso_utc
from argos_inventory.versioning.snapshots import snapshot_nodes, take_snapshot, verify_snapshot

from .sources import register_catalog_system

pytestmark = pytest.mark.integration

T1 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
T2 = T1 + timedelta(days=1)


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        self.events.append((subject, event_type, data))
        return len(self.events)


def _run(dsn: str, system_id: str, started: datetime, prev: str | None) -> str:
    run_id = str(uuid.uuid4())
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.scan_runs "
            "(id, system_id, status, started_at, finished_at, prev_run) "
            "VALUES (%s, %s, 'completed', %s, %s, %s)",
            (run_id, system_id, started, started + timedelta(minutes=5), prev),
        )
    return run_id


def _table(
    system_id: str, run_id: str, at: datetime, table: str, rows: int, columns: list[str]
) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "run_id": run_id,
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": f"probe-{table}",
        "journal_seq": 1,
        "observed_at": iso_utc(at + timedelta(seconds=30)),
        "schema": "clinic",
        "table": table,
        "est_rows": rows,
        "bytes": 8192,
        "comment": None,
        "columns": [{"name": c, "type": "TEXT", "nullable": True} for c in columns],
    }


def _ingest_all(ingestor: Ingestor, events: list[dict[str, Any]]) -> None:
    async def go() -> None:
        for data in events:
            await ingestor.handle(data, {"type": "eu.argos.discovery.table_found.v1"})

    asyncio.run(go())


def _two_runs(dsn: str) -> tuple[str, str, str, GraphStore]:
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    store = GraphStore(dsn)
    ingestor = Ingestor(store, dsn, RecordingBus())
    run1 = _run(dsn, system_id, T1, None)
    _ingest_all(
        ingestor,
        [
            _table(system_id, run1, T1, "appointments", 20000, ["id", "department"]),
            _table(system_id, run1, T1, "readmission_risk", 5000, ["patient_id", "risk_score"]),
        ],
    )
    run2 = _run(dsn, system_id, T2, run1)
    _ingest_all(
        ingestor,
        [
            _table(system_id, run2, T2, "appointments", 70000, ["id", "department"]),
            _table(system_id, run2, T2, "referrals", 10, ["id", "referred_at"]),
        ],
    )
    return system_id, run1, run2, store


def test_first_completed_run_is_the_baseline(migrated_db: str) -> None:
    system_id, run1, _, store = _two_runs(migrated_db)
    bus = RecordingBus()
    report = compute_deltas(store, migrated_db, bus, system_id, run1)
    assert report.baseline is True and report.deltas == ()
    assert bus.events == []


def test_second_run_reports_exactly_what_changed(migrated_db: str) -> None:
    system_id, _, run2, store = _two_runs(migrated_db)
    bus = RecordingBus()
    report = compute_deltas(store, migrated_db, bus, system_id, run2)
    found = {(d.kind, d.label, d.detail["qualified_name"]) for d in report.deltas}
    assert found == {
        ("appeared", "Table", "clinic.referrals"),
        ("appeared", "Column", "clinic.referrals.id"),
        ("appeared", "Column", "clinic.referrals.referred_at"),
        ("disappeared", "Table", "clinic.readmission_risk"),
        ("disappeared", "Column", "clinic.readmission_risk.patient_id"),
        ("disappeared", "Column", "clinic.readmission_risk.risk_score"),
        ("anomalous_growth", "Table", "clinic.appointments"),
    }
    growth = next(d for d in report.deltas if d.kind == "anomalous_growth")
    assert (growth.detail["before"], growth.detail["now"]) == (20000, 70000)
    assert report.counts == {"appeared": 3, "disappeared": 3, "anomalous_growth": 1}
    assert bus.events == [
        (
            "argos.discovery.delta_ready",
            "discovery.delta_ready.v1",
            {"system_id": system_id, "run_id": run2, "counts": report.counts},
        )
    ]
    [row] = store.query(
        "MATCH (t:Table {key: $key}) RETURN t.missing, t.missing_since",
        {"key": table_key(system_id, "clinic", "readmission_risk")},
        ("missing", "since"),
    )
    assert row == {"missing": True, "since": iso_utc(T2)}


def test_deltas_are_stored_journaled_and_idempotent(migrated_db: str) -> None:
    system_id, _, run2, store = _two_runs(migrated_db)
    compute_deltas(store, migrated_db, RecordingBus(), system_id, run2)
    again = compute_deltas(store, migrated_db, RecordingBus(), system_id, run2)
    with psycopg.connect(migrated_db) as conn:
        stored = conn.execute(
            "SELECT kind, count(*) FROM argos.inventory_deltas WHERE run_id = %s GROUP BY kind",
            (run2,),
        ).fetchall()
        journal = conn.execute(
            "SELECT actor, payload->>'run_id' FROM argos.audit_journal "
            "WHERE action = 'inventory.delta'"
        ).fetchall()
    assert dict(stored) == {"appeared": 3, "disappeared": 3, "anomalous_growth": 1}
    # QA-030: a retry gives back the same report and journals nothing twice; it used to find the
    # tables already marked and lose the disappearances.
    assert journal == [("system:inventory", run2)]
    assert again.counts == {"appeared": 3, "disappeared": 3, "anomalous_growth": 1}


def test_failed_runs_are_refused(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    run_id = str(uuid.uuid4())
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at, finished_at, error) "
            "VALUES (%s, %s, 'failed', now(), now(), 'ValueError')",
            (run_id, system_id),
        )
    with pytest.raises(ValueError, match="completed"):
        compute_deltas(GraphStore(migrated_db), migrated_db, RecordingBus(), system_id, run_id)


def test_snapshot_is_a_frozen_photo_while_the_graph_keeps_changing(migrated_db: str) -> None:
    system_id, _, run2, store = _two_runs(migrated_db)
    snapshot = take_snapshot(store, migrated_db, "before-campaign")
    frozen = snapshot_nodes(migrated_db, snapshot.id)
    names = {n["qualified_name"] for n in frozen if n["label"] == "Table"}
    assert names == {"clinic.appointments", "clinic.readmission_risk", "clinic.referrals"}
    assert snapshot.node_count == len(frozen)

    ingestor = Ingestor(store, migrated_db, RecordingBus())
    _ingest_all(ingestor, [_table(system_id, run2, T2, "late_table", 1, ["id"])])
    assert snapshot_nodes(migrated_db, snapshot.id) == frozen
    assert verify_snapshot(migrated_db, snapshot.id) is True

    with psycopg.connect(migrated_db) as conn:
        journal = conn.execute(
            "SELECT payload->>'snapshot_id', payload->>'content_hash' FROM argos.audit_journal "
            "WHERE action = 'inventory.snapshot'"
        ).fetchall()
    assert journal == [(snapshot.id, snapshot.content_hash)]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE argos.inventory_snapshots SET label = 'x'",
        "DELETE FROM argos.inventory_snapshots",
        "TRUNCATE argos.inventory_snapshots CASCADE",
        "UPDATE argos.inventory_snapshot_nodes SET name = 'x'",
        "DELETE FROM argos.inventory_snapshot_nodes",
    ],
)
def test_snapshots_are_immutable(migrated_db: str, statement: str) -> None:
    _, _, _, store = _two_runs(migrated_db)
    take_snapshot(store, migrated_db, "immutable")
    with (
        psycopg.connect(migrated_db) as conn,
        pytest.raises(psycopg.errors.RaiseException, match="immutable"),
    ):
        conn.execute(statement)


# --- QA-26 --------------------------------------------------------------------------------


def _access(system_id: str, run_id: str, at: datetime, table: str, grantee: str) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "run_id": run_id,
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": f"probe-access-{table}",
        "journal_seq": 1,
        "observed_at": iso_utc(at + timedelta(seconds=40)),
        "schema": "clinic",
        "table": table,
        "grants": [{"grantee": grantee, "privilege": "SELECT"}],
    }


def _handle(ingestor: Ingestor, event_type: str, data: dict[str, Any]) -> None:
    asyncio.run(ingestor.handle(data, {"type": f"eu.argos.{event_type}"}))


def test_a_revoked_access_disappears_like_a_table(migrated_db: str) -> None:
    """QA-032: a grant not seen again is marked, and the role with it."""
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    run1 = _run(migrated_db, system_id, T1, None)
    _ingest_all(ingestor, [_table(system_id, run1, T1, "appointments", 10, ["id"])])
    _handle(
        ingestor, "discovery.access_found.v1", _access(system_id, run1, T1, "appointments", "app")
    )
    run2 = _run(migrated_db, system_id, T2, run1)
    _ingest_all(ingestor, [_table(system_id, run2, T2, "appointments", 10, ["id"])])
    report = compute_deltas(store, migrated_db, RecordingBus(), system_id, run2)
    gone = {(d.label, d.detail["name"]) for d in report.deltas if d.kind == "disappeared"}
    assert ("CAN_ACCESS", "app") in gone and ("Identity", "app") in gone
    [edge] = store.query(
        "MATCH (:Identity)-[a:CAN_ACCESS]->(:Table) RETURN a.missing", columns=("missing",)
    )
    assert edge == {"missing": True}


def test_a_redelivered_event_does_not_erase_the_growth(migrated_db: str) -> None:
    """QA-039: the previous size is the one of the previous run, however many times an event of
    this run arrives."""
    system_id, _, run2, store = _two_runs(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    again = _table(system_id, run2, T2, "appointments", 70000, ["id", "department"])
    _ingest_all(ingestor, [again, again])
    report = compute_deltas(store, migrated_db, RecordingBus(), system_id, run2)
    assert report.counts["anomalous_growth"] == 1


def test_an_old_event_does_not_move_last_seen_back(migrated_db: str) -> None:
    system_id, run1, _, store = _two_runs(migrated_db)
    ingestor = Ingestor(store, migrated_db, RecordingBus())
    _ingest_all(ingestor, [_table(system_id, run1, T1, "appointments", 20000, ["id"])])
    [row] = store.query(
        "MATCH (t:Table {key: $key}) RETURN t.last_seen",
        {"key": table_key(system_id, "clinic", "appointments")},
        ("seen",),
    )
    assert row["seen"] == iso_utc(T2 + timedelta(seconds=30))


def test_a_closed_snapshot_takes_no_more_nodes(migrated_db: str) -> None:
    """QA-040: the nodes of a snapshot are written when it is taken, never afterwards."""
    _two_runs(migrated_db)
    snapshot = take_snapshot(GraphStore(migrated_db), migrated_db, "closed")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "INSERT INTO argos.inventory_snapshot_nodes (snapshot_id, node_key, label, name,"
            " qualified_name, system_id, categories)"
            " SELECT snapshot_id, node_key || '-planted', label, name, qualified_name, system_id,"
            " categories FROM argos.inventory_snapshot_nodes WHERE snapshot_id = %s LIMIT 1",
            (snapshot.id,),
        )
    assert verify_snapshot(migrated_db, snapshot.id) is True


def test_a_run_abandoned_in_running_does_not_block_its_system(migrated_db: str) -> None:
    """QA-031: a run still `running` long after the scan timeout is closed as failed."""
    from argos_inventory.scheduler.activities import InventoryActivities

    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    run_id = str(uuid.uuid4())
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at)"
            " VALUES (%s, %s, 'running', now() - interval '6 hours')",
            (run_id, system_id),
        )
    activities = InventoryActivities(migrated_db, None, RecordingBus())  # type: ignore[arg-type]
    [state] = [s for s in activities._states(datetime.now(UTC)) if s.system_id == system_id]
    assert state.running is False
    with psycopg.connect(migrated_db) as conn:
        status, error = conn.execute(
            "SELECT status, error FROM argos.scan_runs WHERE id = %s", (run_id,)
        ).fetchone()  # type: ignore[misc]
    assert status == "failed" and "abandoned" in error
