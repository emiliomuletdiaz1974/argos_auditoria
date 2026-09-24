"""ARG-100 · the facts ARGOS publishes about itself for its self-* challenges (F10-01).

`argos_facts.facts` answers, as `(fact, setting)` rows, what a configuration check of the
appliance needs: whether the journal and the security log verify, whether a restore was tested,
whether every connection is encrypted and whether signed content is in force. The self-* challenges
read it with the SQL connector and the read-only role `svc_selfcheck`, which reads the facts and
nothing behind them.
"""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from argos_common.journal_pg import PostgresJournal
from argos_common.security_log import log as security_log

pytestmark = pytest.mark.integration


def _facts(dsn: str, role: str | None = None) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        if role is not None:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        rows = conn.execute("SELECT fact, setting FROM argos_facts.facts").fetchall()
    return {str(fact): str(setting) for fact, setting in rows}


def _tamper(dsn: str, schema: str, table: str, seq: int) -> None:
    """What an attacker with the owner's hands would do: switch the guard off and edit a row."""
    name = sql.Identifier(schema, table)
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(name))
        conn.execute(
            sql.SQL("UPDATE {} SET payload_canon = payload_canon || ' ' WHERE seq = %s").format(
                name
            ),
            (seq,),
        )
        conn.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(name))


def _restore_test(dsn: str, when: datetime, result: str) -> None:
    intact = result == "passed"
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.restore_tests (tested_at, result, journal_intact, security_intact,"
            " duration_seconds) VALUES (%s, %s, %s, %s, 1)",
            (when, result, intact, intact),
        )


def test_a_fresh_appliance_answers_every_fact(migrated_db: str) -> None:
    facts = _facts(migrated_db)
    assert set(facts) == {
        "journal_tail_intact",
        "security_log_intact",
        "restore_test_recent",
        "connections_encrypted",
        "signed_content_in_force",
        "selfcheck_trap",
    }
    assert facts["journal_tail_intact"] == "true"
    assert facts["security_log_intact"] == "true"
    # Nothing was restored nor loaded yet: the facts say so, they do not assume.
    assert facts["restore_test_recent"] == "false"
    assert facts["signed_content_in_force"] == "false"
    assert facts["selfcheck_trap"] == "tripped"


def test_the_journal_verifies_and_one_edited_entry_breaks_it(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    for n in range(5):
        journal.append("user:tester", "test.selfcheck", {"n": n})
    assert _facts(migrated_db)["journal_tail_intact"] == "true"
    _tamper(migrated_db, "argos", "audit_journal", 3)
    assert _facts(migrated_db)["journal_tail_intact"] == "false"
    # The fact agrees with the verifier of the journal v1.
    assert not journal.verify().intact


def test_the_security_log_verifies_and_one_edited_event_breaks_it(migrated_db: str) -> None:
    events = security_log(migrated_db)
    for n in range(3):
        events.record("auth.login", f"user:tester-{n}", "refused", {"n": n}, source="tests")
    assert _facts(migrated_db)["security_log_intact"] == "true"
    _tamper(migrated_db, "security", "events", 2)
    assert _facts(migrated_db)["security_log_intact"] == "false"


def test_only_a_recent_passed_restore_counts(migrated_db: str) -> None:
    now = datetime.now(UTC)
    _restore_test(migrated_db, now - timedelta(days=40), "passed")
    assert _facts(migrated_db)["restore_test_recent"] == "false"
    _restore_test(migrated_db, now - timedelta(days=2), "passed")
    assert _facts(migrated_db)["restore_test_recent"] == "true"
    # The last test is the one that counts: a failure after a success is a failure.
    _restore_test(migrated_db, now - timedelta(days=1), "failed")
    assert _facts(migrated_db)["restore_test_recent"] == "false"


def test_the_selfcheck_role_reads_the_facts_and_nothing_behind_them(migrated_db: str) -> None:
    assert _facts(migrated_db, role="svc_selfcheck")["journal_tail_intact"] == "true"
    with psycopg.connect(migrated_db) as conn:
        conn.execute("SET ROLE svc_selfcheck")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT payload FROM argos.audit_journal LIMIT 1")
    with psycopg.connect(migrated_db) as conn:
        writable = conn.execute(
            "SELECT count(*) FROM information_schema.role_table_grants"
            " WHERE grantee = 'svc_selfcheck' AND privilege_type <> 'SELECT'"
        ).fetchone()
        views = conn.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.role_table_grants"
            " WHERE grantee = 'svc_selfcheck'"
        ).fetchall()
        functions = conn.execute(
            "SELECT p.oid::regprocedure::text FROM pg_proc p"
            " JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')"
            " AND NOT has_function_privilege('public', p.oid, 'EXECUTE')"
            " AND has_function_privilege('svc_selfcheck', p.oid, 'EXECUTE')"
        ).fetchall()
        schema_argos = conn.execute(
            "SELECT has_schema_privilege('svc_selfcheck', 'argos', 'USAGE')"
        ).fetchone()
    assert writable == (0,)
    assert [row[0] for row in views] == ["argos_facts.facts"]
    # Beyond what anybody may run, only the function that computes the facts.
    assert [row[0] for row in functions] == ["argos_facts.compute()"]
    assert schema_argos == (False,)


def test_the_trap_cannot_be_switched_off_by_configuration(migrated_db: str) -> None:
    # The trap is a constant of the function: no setting, table or role changes its answer.
    with psycopg.connect(migrated_db) as conn:
        definition = conn.execute(
            "SELECT pg_get_functiondef('argos_facts.compute()'::regprocedure)"
        ).fetchone()
    assert definition is not None
    assert "'tripped'" in str(definition[0])
