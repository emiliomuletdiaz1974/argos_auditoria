"""Journal v1 against PostgreSQL: Phase 1 acceptance and concurrency (ADR-0002)."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from argos_common.journal import GENESIS
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration


def test_one_hundred_intact_entries(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    base, _ = journal.head()  # the migration already wrote its own entry
    for i in range(100):
        journal.append("system:test", "test.write", {"i": i})
    r = journal.verify()
    assert r.intact
    assert r.verified == base + 100
    assert journal.head()[0] == base + 100


def test_on_disk_corruption_reports_the_position(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    for i in range(50):
        journal.append("system:test", "test.write", {"i": i})
    with psycopg.connect(migrated_db, autocommit=True) as c:  # a malicious DBA bypasses the trigger
        c.execute("ALTER TABLE argos.audit_journal DISABLE TRIGGER journal_no_update")
        c.execute("UPDATE argos.audit_journal SET payload_canon = '{\"i\":999}' WHERE seq = 37")
        c.execute("ALTER TABLE argos.audit_journal ENABLE TRIGGER journal_no_update")
    r = journal.verify()
    assert not r.intact
    assert r.anomalies[0].seq == 37


def test_concurrent_writes_do_not_fork_the_chain(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    base, _ = journal.head()

    def write(thread: int) -> None:
        for i in range(25):
            journal.append(f"system:thread{thread}", "test.concurrency", {"i": i})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(8)))
    r = journal.verify()
    assert r.intact, r.anomalies[:3]
    assert r.head_seq == base + 200


def test_caller_rollback_leaves_no_gaps(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    base, _ = journal.head()
    with psycopg.connect(migrated_db) as conn:
        journal.append("system:test", "test.rollback", {"x": 1}, conn=conn)
        conn.rollback()
    seq = journal.append("system:test", "test.after_rollback", {"x": 2})
    assert seq == base + 1
    assert journal.verify().intact


def test_range_verification(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    for i in range(20):
        journal.append("system:test", "test.range", {"i": i})
    r = journal.verify(from_seq=10, to_seq=15)
    assert r.intact and r.verified == 6 and r.head_seq == 15


def test_head_of_empty_journal(empty_db: str) -> None:
    with psycopg.connect(empty_db, autocommit=True) as c:
        c.execute("CREATE SCHEMA argos")
        c.execute(
            "CREATE TABLE argos.audit_journal (seq bigint, at_canon text, actor text, action text,"
            " payload_canon text, prev_hash bytea, entry_hash bytea)"
        )
    assert PostgresJournal(empty_db).head() == (0, GENESIS)


def test_float_payload_never_reaches_the_database(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    base, _ = journal.head()
    with pytest.raises(ValueError):
        journal.append("system:test", "test.float", {"x": 1.5})
    assert journal.head()[0] == base
