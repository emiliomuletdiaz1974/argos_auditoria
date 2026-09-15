"""PostgreSQL connector (ARG-015): catalogue and checks are read-only literal SQL."""

import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.readonly import validate_read_only_sql
from argos_connector.testing import assert_no_write_surface, make_context
from argos_sql.postgres import CATALOG_SQL, PostgresConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"


@pytest.mark.parametrize("name", sorted(PostgresConnector.CONFIG_CHECKS))
def test_named_checks_are_read_only_sql(name: str) -> None:
    validate_read_only_sql(PostgresConnector.CONFIG_CHECKS[name].sql, "postgres")


def test_catalog_query_is_read_only_sql() -> None:
    validate_read_only_sql(CATALOG_SQL, "postgres")


def test_scan_schema_journals_the_catalog_query() -> None:
    connector = PostgresConnector(SYSTEM_ID, {}, make_context())
    rendered = connector.render(ProbeSpec("scan_schema", "clinic"))
    assert rendered.statement == CATALOG_SQL


def test_privileges_check_binds_schema_and_table() -> None:
    connector = PostgresConnector(SYSTEM_ID, {}, make_context())
    params = {"check": "privileges", "schema": "clinic", "table": "patients"}
    rendered = connector.render(ProbeSpec("check_config", "clinic.patients", params=params))
    assert rendered.params["binds"] == {"schema": "clinic", "table": "patients"}
    assert rendered.statement == PostgresConnector.CONFIG_CHECKS["privileges"].sql


def test_no_write_surface() -> None:
    assert_no_write_surface(PostgresConnector)
