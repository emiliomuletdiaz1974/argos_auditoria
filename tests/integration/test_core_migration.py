"""ARG-005 · core migration, migrator and journal guarantees inside the database engine."""

import json
import shutil
from pathlib import Path
from typing import Any

import psycopg
import pytest

from argos_common.errors import IntegrityError
from argos_common.migrations import apply_migrations

from .conftest import MIGRATIONS_DIR

pytestmark = pytest.mark.integration

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "vectors" / "journal_v1.json").read_text(encoding="utf-8")
)


def test_applies_once_and_is_idempotent(empty_db: str) -> None:
    assert apply_migrations(empty_db, MIGRATIONS_DIR) == [1, 2]
    assert apply_migrations(empty_db, MIGRATIONS_DIR) == []
    with psycopg.connect(empty_db) as c:
        assert c.execute("SELECT count(*) FROM argos.schema_version").fetchone() == (2,)
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
        assert seq == (3,)
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
