"""ARG-012 · prior query journal on PostgreSQL: one transaction, literal statement, single close."""

import json
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from argos_common.errors import IntegrityError
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_connector.base import Connector
from argos_connector.journal import QueryJournal, statement_hash
from argos_connector.probes import ProbeSpec
from argos_connector.testing import NoBudget, make_context

pytestmark = pytest.mark.integration

SPEC = ProbeSpec(
    "count",
    "clinic.patients",
    "SELECT count(*) AS n FROM clinic.patients WHERE created_at < :cutoff",
    {"binds": {"cutoff": "2020-01-01"}},
)


def _register_system(dsn: str) -> str:
    system_id = str(uuid7())
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, connection) VALUES (%s, %s, 'rdbms', '{}')",
            (system_id, "test-system"),
        )
    return system_id


def _row(dsn: str, seq: int) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM argos.connector_queries WHERE journal_seq = %s", (seq,)
        ).fetchone()
    assert row is not None
    return row


@pytest.fixture
def system_id(migrated_db: str) -> str:
    return _register_system(migrated_db)


def test_register_writes_entry_and_row_together(migrated_db: str, system_id: str) -> None:
    seq = QueryJournal(migrated_db, system_id).register(SPEC)
    entry = next(PostgresJournal(migrated_db).read(from_seq=seq, to_seq=seq))
    assert entry.action == "query.emit"
    assert entry.actor == f"system:connector:{system_id}"
    assert json.loads(entry.payload_canon) == {
        "kind": "count",
        "stmt_sha256": statement_hash(SPEC.statement).hex(),
        "system_id": system_id,
        "target": "clinic.patients",
    }
    row = _row(migrated_db, seq)
    assert row["status"] == "emitted" and row["finished_at"] is None
    assert row["statement"] == SPEC.statement
    assert row["params"] == {"binds": {"cutoff": "2020-01-01"}}


def test_complete_closes_the_row_exactly_once(migrated_db: str, system_id: str) -> None:
    journal = QueryJournal(migrated_db, system_id)
    seq = journal.register(SPEC)
    journal.complete(seq, ok=True, duration_ms=12, rows=5000)
    row = _row(migrated_db, seq)
    assert (row["status"], row["ok"], row["duration_ms"], row["rows_touched"]) == (
        "completed",
        True,
        12,
        5000,
    )
    with pytest.raises(IntegrityError):
        journal.complete(seq, ok=True, duration_ms=1, rows=1)


def test_failed_probe_keeps_its_error_type(migrated_db: str, system_id: str) -> None:
    journal = QueryJournal(migrated_db, system_id)
    seq = journal.register(SPEC)
    journal.complete(seq, ok=False, duration_ms=3, rows=0, error="OperationalError")
    row = _row(migrated_db, seq)
    assert (row["status"], row["error"]) == ("failed", "OperationalError")


def test_rejected_attempt_is_journaled_and_closed(migrated_db: str, system_id: str) -> None:
    spec = ProbeSpec("check_config", "t", "DELETE FROM t")
    seq = QueryJournal(migrated_db, system_id).reject(spec, "forbidden construct: Delete")
    entry = next(PostgresJournal(migrated_db).read(from_seq=seq, to_seq=seq))
    assert entry.action == "query.reject"
    assert json.loads(entry.payload_canon)["reason"] == "forbidden construct: Delete"
    row = _row(migrated_db, seq)
    assert row["status"] == "rejected" and row["ok"] is False and row["finished_at"] is not None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE argos.connector_queries SET statement = 'SELECT 1'",
        "UPDATE argos.connector_queries SET journal_seq = journal_seq + 1000",
        "DELETE FROM argos.connector_queries",
    ],
)
def test_registered_query_cannot_be_rewritten(
    migrated_db: str, system_id: str, statement: str
) -> None:
    QueryJournal(migrated_db, system_id).register(SPEC)
    with (
        psycopg.connect(migrated_db) as conn,
        pytest.raises(psycopg.errors.RaiseException, match="connector_queries"),
    ):
        conn.execute(statement)


def test_unknown_system_leaves_no_journal_entry(migrated_db: str) -> None:
    head_before = PostgresJournal(migrated_db).head()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        QueryJournal(migrated_db, str(uuid7())).register(SPEC)
    assert PostgresJournal(migrated_db).head() == head_before


class ProbeRecorder(Connector):
    kind = "test"

    def __init__(self, dsn: str, *args: Any) -> None:
        super().__init__(*args)
        self.dsn = dsn
        self.open_rows_seen: list[int] = []

    def _look(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT count(*) FROM argos.connector_queries "
                "WHERE system_id = %s AND status = 'emitted'",
                (self.system_id,),
            ).fetchone()
        assert row is not None
        self.open_rows_seen.append(int(row[0]))
        return {"ok": True}, 1

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._look(spec)

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._look(spec)

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._look(spec)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._look(spec)


def test_connector_is_journaled_before_it_touches_the_system(
    migrated_db: str, system_id: str
) -> None:
    context = make_context(journal=QueryJournal(migrated_db, system_id), budget=NoBudget())
    connector = ProbeRecorder(migrated_db, system_id, {}, context)
    result = connector.execute(ProbeSpec("scan_schema", "clinic"))
    assert connector.open_rows_seen == [1]
    assert _row(migrated_db, result.journal_seq)["status"] == "completed"
    assert PostgresJournal(migrated_db).verify().intact
