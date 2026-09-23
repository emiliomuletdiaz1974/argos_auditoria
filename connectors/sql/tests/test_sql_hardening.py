"""ARG-014…016 · what the security review F09-02 found in the SQL connectors.

- SEC-022: `check_config` reads configuration, not the client's tables, and never brings a value in
  clear that is not a setting.
- SEC-024: a name the client chose (`año-2024`, `Pacientes.2024`) is quoted, not refused.
- SEC-027: SQL Server travels with verified TLS through ODBC Driver 18; pymssql only with
  `allow_insecure` declared.
- SEC-054: the privileges of a table are asked by its oid, not by its name as text.
"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from argos_common.errors import ConfigurationError
from argos_connector.config_sources import check_config_sources
from argos_connector.probes import ProbeSpec
from argos_connector.testing import InMemoryJournal, NoBudget, make_context
from argos_sql.generic import SqlConnector, driver_options, transport_encrypted
from argos_sql.mssql import MssqlConnector
from argos_sql.postgres import PRIVILEGES_SQL

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "clinic.db"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("CREATE TABLE patients (id INTEGER PRIMARY KEY, national_id TEXT)")
        conn.executemany(
            "INSERT INTO patients VALUES (?, ?)", [(i, f"SYN{i:08d}") for i in range(1, 51)]
        )
        conn.execute('CREATE TABLE "año-2024" (id INTEGER, "col\x1fumn" TEXT)')
        conn.execute("INSERT INTO \"año-2024\" VALUES (1, 'x')")
    conn.close()
    return path


def _open(db: Path, max_rows: int = 10_000) -> tuple[SqlConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    context = make_context(
        {"url": f"sqlite:///{db.as_posix()}"}, journal=journal, budget=NoBudget(max_rows)
    )
    connector = SqlConnector(SYSTEM_ID, {"statement_timeout_ms": 5000}, context)
    connector.open()
    return connector, journal


# ---------- SEC-022 · configuration, not business rows ----------


def test_a_check_on_a_business_table_is_refused_before_journaling(db: Path) -> None:
    connector, journal = _open(db)
    with pytest.raises(ValueError, match="configuration"):
        connector.execute(ProbeSpec("check_config", "patients", "SELECT national_id FROM patients"))
    assert journal.records == []


def test_a_value_that_is_not_a_setting_travels_as_a_digest(db: Path) -> None:
    connector, _ = _open(db)
    result = connector.execute(
        ProbeSpec(
            "check_config",
            "catalog",
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name",
        )
    )
    first = next(row for row in result.data["rows"] if row["name"] == "patients")
    assert "national_id" not in str(result.data)  # the DDL is not a setting: digest only
    assert len(first["sql"]) == 32


def test_a_check_brings_at_most_the_rows_of_the_budget(db: Path) -> None:
    connector, _ = _open(db, max_rows=1)
    result = connector.execute(
        ProbeSpec("check_config", "catalog", "SELECT name FROM sqlite_master WHERE type = 'table'")
    )
    assert len(result.data["rows"]) == 1


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT setting FROM pg_settings WHERE name = 'ssl'", "postgres"),
        ("SELECT r.rolname FROM pg_roles AS r, pg_class AS c", "postgres"),
        ("SELECT IF(@@global.require_secure_transport, 'on', 'off') AS setting", "mysql"),
        ("SELECT privilege_type FROM information_schema.table_privileges", "mysql"),
        ("SELECT name FROM sys.server_audits", "tsql"),
        ("SELECT username FROM dba_users", "oracle"),
    ],
)
def test_catalogue_and_configuration_sources_are_accepted(statement: str, dialect: str) -> None:
    check_config_sources(statement, dialect)


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT dni, diagnostico FROM pacientes", "postgres"),
        ("SELECT * FROM clinic.patients", "postgres"),
        ("SELECT s.setting FROM pg_settings s JOIN billing.invoices i ON true", "postgres"),
        ("SELECT amount FROM billing.invoices", "mysql"),
    ],
)
def test_a_business_table_is_not_a_configuration_source(statement: str, dialect: str) -> None:
    with pytest.raises(ValueError, match="configuration"):
        check_config_sources(statement, dialect)


# ---------- SEC-024 · the client's names are quoted, not refused ----------


def test_a_table_with_a_non_ascii_name_is_counted(db: Path) -> None:
    connector, _ = _open(db)
    assert connector.execute(ProbeSpec("count", "main.año-2024")).data == {"count": 1}


def test_a_name_with_a_dot_keeps_its_schema() -> None:
    table = SqlConnector._split_target("public.Pacientes.2024")
    assert table == ("public", "Pacientes.2024")


def test_a_control_character_in_a_name_is_still_refused(db: Path) -> None:
    connector, journal = _open(db)
    with pytest.raises(ValueError, match="identifier"):
        connector.execute(ProbeSpec("sample", "patients\x00", params={"columns": ["id"]}))
    assert journal.records == []


# ---------- SEC-027 · SQL Server with verified TLS ----------


@pytest.mark.parametrize(
    ("url", "encrypted"),
    [
        (
            "mssql+pyodbc://u@h:1433/db?driver=ODBC+Driver+18+for+SQL+Server"
            "&Encrypt=yes&TrustServerCertificate=no",
            True,
        ),
        (
            "mssql+pyodbc://u@h:1433/db?driver=ODBC+Driver+18+for+SQL+Server"
            "&Encrypt=yes&TrustServerCertificate=yes",
            False,
        ),
        ("mssql+pyodbc://u@h:1433/db?driver=ODBC+Driver+18+for+SQL+Server", True),
        ("mssql+pymssql://u@h/db?encrypt=yes", False),
    ],
)
def test_sql_server_counts_as_encrypted_only_when_it_verifies(url: str, encrypted: bool) -> None:
    assert transport_encrypted(url) is encrypted


def test_pymssql_without_a_declaration_is_refused_at_open() -> None:
    context = make_context({"url": "mssql+pymssql://u:p@127.0.0.1:1/db"})
    connector = MssqlConnector(SYSTEM_ID, {}, context)
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        connector.open()


def test_odbc_takes_its_login_timeout() -> None:
    options = driver_options(make_url("mssql+pyodbc://u@h/db"), 30_000)
    assert options == {"connect_args": {"timeout": 30}}


# ---------- SEC-054 · privileges by oid ----------


def test_the_privileges_of_a_table_are_asked_by_its_oid() -> None:
    assert "has_table_privilege(r.rolname, c.oid, 'SELECT')" in PRIVILEGES_SQL
    assert "|| '.' ||" not in PRIVILEGES_SQL
