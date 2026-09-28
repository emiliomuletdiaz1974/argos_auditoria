"""ARG-005 · core migration, migrator and journal guarantees inside the database engine."""

import json
import shutil
from pathlib import Path
from typing import Any

import psycopg
import pytest

from argos_common.errors import IntegrityError
from argos_common.migrations import apply_migrations, list_migrations

from .conftest import MIGRATIONS_DIR

pytestmark = pytest.mark.integration

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "vectors" / "journal_v1.json").read_text(encoding="utf-8")
)
EXPECTED_VERSIONS = [version for version, _ in list_migrations(MIGRATIONS_DIR)]


def test_applies_once_and_is_idempotent(empty_db: str) -> None:
    assert apply_migrations(empty_db, MIGRATIONS_DIR) == EXPECTED_VERSIONS
    assert apply_migrations(empty_db, MIGRATIONS_DIR) == []
    with psycopg.connect(empty_db) as c:
        count = c.execute("SELECT count(*) FROM argos.schema_version").fetchone()
        assert count == (len(EXPECTED_VERSIONS),)
        row = c.execute(
            "SELECT seq, actor, action, payload FROM argos.audit_journal ORDER BY seq"
        ).fetchone()
    assert row is not None
    assert row[:3] == (1, "system:migrator", "schema.migrate")
    assert row[3]["version"] == 1


def test_migration_modified_after_being_applied(empty_db: str, tmp_path: Path) -> None:
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    apply_migrations(empty_db, copy)
    with (copy / "0001_core.sql").open("a", encoding="utf-8") as f:
        f.write("\n-- later change\n")
    with pytest.raises(IntegrityError, match="0001|1"):
        apply_migrations(empty_db, copy)


@pytest.mark.parametrize("v", VECTORS["entries"], ids=lambda v: f"seq{v['seq']}")
def test_sql_journal_hash_reproduces_the_vectors(empty_db: str, v: dict[str, Any]) -> None:
    apply_migrations(empty_db, MIGRATIONS_DIR)
    with psycopg.connect(empty_db) as c:
        row = c.execute(
            "SELECT argos.journal_hash(%s, %s, %s, %s, %s, %s)",
            (
                v["seq"],
                v["at_canon"],
                v["actor"],
                v["action"],
                v["payload_canon"],
                bytes.fromhex(v["prev_hash"]),
            ),
        ).fetchone()
    assert row is not None and bytes(row[0]).hex() == v["entry_hash"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE argos.audit_journal SET actor = 'x'",
        "DELETE FROM argos.audit_journal",
        "TRUNCATE argos.audit_journal",
    ],
)
def test_journal_is_immutable(empty_db: str, statement: str) -> None:
    apply_migrations(empty_db, MIGRATIONS_DIR)
    with (
        psycopg.connect(empty_db) as c,
        pytest.raises(psycopg.errors.RaiseException, match="immutable"),
    ):
        c.execute(statement)


def test_service_role_can_only_write_through_journal_append(empty_db: str) -> None:
    apply_migrations(empty_db, MIGRATIONS_DIR)
    with psycopg.connect(empty_db, autocommit=True) as c:
        c.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'svc_test')"
            " THEN CREATE ROLE svc_test NOLOGIN; END IF; END $$"
        )
        c.execute("GRANT USAGE ON SCHEMA argos TO svc_test")
        c.execute("GRANT EXECUTE ON FUNCTION argos.journal_append(text, text, text) TO svc_test")
    with psycopg.connect(empty_db) as c:
        c.execute("SET ROLE svc_test")
        seq = c.execute("SELECT argos.journal_append('system:svc', 'test.ok', '{}')").fetchone()
        assert seq == (len(EXPECTED_VERSIONS) + 1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "INSERT INTO argos.audit_journal VALUES "
                "(99, now(), 'x', 'x', 'x', '{}', '{}', '\\x00', '\\x00')"
            )


def test_at_canon_has_canonical_format(empty_db: str) -> None:
    apply_migrations(empty_db, MIGRATIONS_DIR)
    with psycopg.connect(empty_db) as c:
        row = c.execute("SELECT at_canon FROM argos.audit_journal WHERE seq = 1").fetchone()
    assert row is not None
    assert len(row[0]) == 27 and row[0].endswith("Z") and row[0][10] == "T"


# --- Quality review QA-01: QA-012, QA-014 -------------------------------------------------------


def test_a_database_ahead_of_the_code_is_said(
    empty_db: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """QA-014: versions applied that this code does not have mean older code on a newer schema."""
    apply_migrations(empty_db, MIGRATIONS_DIR)
    older = tmp_path / "older"
    older.mkdir()
    first = list_migrations(MIGRATIONS_DIR)[0][1]
    shutil.copy(first, older / first.name)
    with caplog.at_level("WARNING", logger="argos_common.migrations"):
        assert apply_migrations(empty_db, older) == []
    assert "not in" in caplog.text and str(EXPECTED_VERSIONS[-1]) in caplog.text


def test_the_error_of_a_migration_is_not_hidden_by_the_cleanup(
    empty_db: str, tmp_path: Path
) -> None:
    """QA-014: a migration that loses its connection must raise its own error, not the one of
    the rollback on a closed connection."""
    apply_migrations(empty_db, MIGRATIONS_DIR)
    broken = tmp_path / "broken"
    broken.mkdir()
    for _, path in list_migrations(MIGRATIONS_DIR):
        shutil.copy(path, broken / path.name)
    (broken / "9999_lost_connection.sql").write_text(
        "SELECT pg_terminate_backend(pg_backend_pid());", encoding="utf-8"
    )
    with pytest.raises(psycopg.OperationalError) as lost:
        apply_migrations(empty_db, broken)
    assert "terminat" in str(lost.value).lower()


def test_the_order_of_the_journal_by_time_is_the_order_by_sequence(empty_db: str) -> None:
    """QA-012: the instant was taken before waiting for the lock, so an entry that waited got an
    earlier `at` than the one that went before it."""
    import threading
    import time

    apply_migrations(empty_db, MIGRATIONS_DIR)
    append_sql = "SELECT argos.journal_append('system:migrator', 'schema.test', '{}')"
    with psycopg.connect(empty_db) as holder:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext('argos.audit_journal'))")

        def waiting() -> None:
            with psycopg.connect(empty_db) as conn:
                conn.execute(append_sql)

        second = threading.Thread(target=waiting)
        second.start()
        time.sleep(1.0)  # the second has taken its instant and waits for the lock
        holder.execute(append_sql)
        holder.commit()
        second.join(timeout=30)
    with psycopg.connect(empty_db) as conn:
        rows = conn.execute(
            "SELECT seq, at FROM argos.audit_journal WHERE action = 'schema.test' ORDER BY seq"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] <= rows[1][1], rows
