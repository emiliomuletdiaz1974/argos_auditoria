"""Oracle and SQL Server connectors (ARG-016): every catalogue query and check is read-only."""

import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.readonly import validate_read_only_sql
from argos_connector.testing import assert_no_write_surface, make_context
from argos_sql.mssql import MssqlConnector
from argos_sql.oracle import SCHEMA_SQL, OracleConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"


@pytest.mark.parametrize("name", sorted(OracleConnector.CONFIG_CHECKS))
def test_oracle_checks_are_read_only(name: str) -> None:
    validate_read_only_sql(OracleConnector.CONFIG_CHECKS[name].sql, "oracle")


@pytest.mark.parametrize("name", sorted(MssqlConnector.CONFIG_CHECKS))
def test_mssql_checks_are_read_only(name: str) -> None:
    validate_read_only_sql(MssqlConnector.CONFIG_CHECKS[name].sql, "tsql")


def test_oracle_scan_uses_the_native_catalog() -> None:
    validate_read_only_sql(SCHEMA_SQL, "oracle")
    connector = OracleConnector(SYSTEM_ID, {}, make_context())
    assert connector.render(ProbeSpec("scan_schema", "*")).statement == SCHEMA_SQL


def test_same_check_names_for_the_challenge_library() -> None:
    expected = {"audit_status", "generic_accounts", "privileged_grants"}
    assert set(OracleConnector.CONFIG_CHECKS) == expected
    assert set(MssqlConnector.CONFIG_CHECKS) == expected


@pytest.mark.parametrize("cls", [OracleConnector, MssqlConnector])
def test_no_write_surface(cls: type) -> None:
    assert_no_write_surface(cls)


def test_sql_server_statements_have_a_deadline() -> None:
    """SEC-006: pymssql waits forever by default; the connector's timeout reaches the driver."""
    from sqlalchemy.engine import make_url

    from argos_sql.generic import driver_options

    pymssql = driver_options(make_url("mssql+pymssql://u@h/db"), 30_000)
    assert pymssql == {"connect_args": {"timeout": 30, "login_timeout": 30}}
    assert driver_options(make_url("mssql+pymssql://u@h/db"), 500) == {
        "connect_args": {"timeout": 1, "login_timeout": 1}
    }
    assert driver_options(make_url("postgresql+psycopg://u@h/db"), 30_000) == {}


def test_oracle_scan_keeps_to_the_schemas_asked_and_to_tables() -> None:
    """QA-024: `params.schemas` narrows the scan as in the other connectors, and views are not
    tables of the client."""
    connector = OracleConnector(SYSTEM_ID, {}, make_context())
    statement = connector.render(ProbeSpec("scan_schema", "*", params={"schemas": ["CLINICA"]}))
    sql = statement.statement or ""
    assert "all_tables" in sql.lower(), "columns of views are not columns of tables"
    assert "'CLINICA'" in sql
    validate_read_only_sql(sql, "oracle")
