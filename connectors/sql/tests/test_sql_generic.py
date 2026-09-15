"""Generic SQL connector (ARG-014) on SQLite: dialect-compiled probes, keyed samples, harness."""

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from argos_common.errors import ReadOnlyViolationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import (
    SQL_WRITE_ATTEMPTS,
    InMemoryJournal,
    NoBudget,
    assert_no_write_surface,
    assert_sql_writes_rejected,
    make_context,
)
from argos_sql.generic import ConfigCheck, SqlConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "clinic.db"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "CREATE TABLE patients (id INTEGER PRIMARY KEY, national_id TEXT NOT NULL, "
            "birth_date TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO patients VALUES (?, ?, ?)",
            [(i, f"SYN{i:08d}", f"19{50 + i % 50}-01-01") for i in range(1, 51)],
        )
    conn.close()
    return path


class CheckedConnector(SqlConnector):
    CONFIG_CHECKS: ClassVar[Mapping[str, ConfigCheck]] = {
        "tables": ConfigCheck("SELECT name FROM sqlite_master WHERE type = :kind", ("kind",)),
    }


def _open(db: Path, budget: NoBudget | None = None) -> tuple[CheckedConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    context = make_context(
        {"url": f"sqlite:///{db.as_posix()}"}, journal=journal, budget=budget or NoBudget()
    )
    connector = CheckedConnector(SYSTEM_ID, {"statement_timeout_ms": 5000}, context)
    connector.open()
    return connector, journal


def test_scan_schema_lists_tables_and_columns(db: Path) -> None:
    connector, _ = _open(db)
    result = connector.execute(ProbeSpec("scan_schema", "*"))
    columns = result.data["schemas"]["main"]["patients"]["columns"]
    assert [c["name"] for c in columns] == ["id", "national_id", "birth_date"]
    assert result.ok and result.rows_touched == 3


def test_count_compiles_the_template_and_journals_it_literally(db: Path) -> None:
    connector, journal = _open(db)
    spec = ProbeSpec(
        "count",
        "patients",
        params={"where": "birth_date < :cutoff", "binds": {"cutoff": "1960-01-01"}},
    )
    result = connector.execute(spec)
    assert result.data == {"count": 10}
    journaled = journal.emitted[0].spec
    assert journaled.statement is not None
    assert "count(*)" in journaled.statement and "birth_date < :cutoff" in journaled.statement
    assert journaled.params["binds"]["cutoff"] == "1960-01-01"


def test_sample_returns_keyed_digests_only(db: Path) -> None:
    connector, _ = _open(db)
    result = connector.execute(
        ProbeSpec("sample", "patients", params={"columns": ["national_id"], "k": 5})
    )
    assert result.data["n"] == 5 and len(result.data["cell_digests"]) == 5
    assert all(len(row[0]) == 32 for row in result.data["cell_digests"])
    assert "SYN" not in repr(result)


def test_sample_is_capped_by_the_budget(db: Path) -> None:
    connector, journal = _open(db, NoBudget(max_rows_per_probe=3))
    result = connector.execute(
        ProbeSpec("sample", "patients", params={"columns": ["id"], "k": 100})
    )
    assert result.data["n"] == 3
    assert "LIMIT 3" in (journal.emitted[0].spec.statement or "")


def test_named_check_and_declared_statement(db: Path) -> None:
    connector, _ = _open(db)
    named = connector.execute(
        ProbeSpec("check_config", "catalog", params={"check": "tables", "kind": "table"})
    )
    assert named.data == {"rows": [{"name": "patients"}]}
    declared = connector.execute(
        ProbeSpec("check_config", "patients", "SELECT count(*) AS n FROM patients")
    )
    assert declared.data == {"rows": [{"n": 50}]}


def test_check_without_statement_is_refused_before_journaling(db: Path) -> None:
    connector, journal = _open(db)
    with pytest.raises(ValueError, match="named check or a declared statement"):
        connector.execute(ProbeSpec("check_config", "patients"))
    with pytest.raises(ValueError, match="unknown configuration check"):
        connector.execute(ProbeSpec("check_config", "x", params={"check": "does_not_exist"}))
    assert journal.records == []


@pytest.mark.parametrize(
    ("target", "columns"),
    [
        ("patients; DROP TABLE patients", ["id"]),
        ("patients", ["national_id FROM x"]),
        ("a.b.c", ["id"]),
    ],
)
def test_invalid_identifiers_are_refused(db: Path, target: str, columns: list[str]) -> None:
    connector, journal = _open(db)
    with pytest.raises(ValueError, match="identifier"):
        connector.execute(ProbeSpec("sample", target, params={"columns": columns}))
    assert journal.records == []


def test_write_harness_rejects_every_attempt_and_the_table_is_intact(db: Path) -> None:
    connector, journal = _open(db)
    assert_sql_writes_rejected(connector, "patients")
    assert len(journal.rejected) == len(SQL_WRITE_ATTEMPTS) and journal.emitted == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM patients").fetchone() == (50,)


def test_session_is_read_only_even_without_the_guard(db: Path) -> None:
    connector, _ = _open(db)
    with connector.engine.connect() as conn, pytest.raises(OperationalError):
        conn.execute(text("INSERT INTO patients VALUES (99, 'x', '2000-01-01')"))
        conn.commit()


def test_no_write_surface() -> None:
    assert_no_write_surface(SqlConnector)


def test_closed_connector_cannot_render(db: Path) -> None:
    context = make_context({"url": f"sqlite:///{db.as_posix()}"})
    with pytest.raises(RuntimeError, match="not open"):
        SqlConnector(SYSTEM_ID, {}, context).execute(ProbeSpec("count", "patients"))


def test_rejection_reason_is_journaled(db: Path) -> None:
    connector, journal = _open(db)
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("check_config", "patients", "DELETE FROM patients"))
    assert journal.rejected[0].outcome is not None
