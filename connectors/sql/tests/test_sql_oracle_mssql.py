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
