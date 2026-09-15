"""ARG-015 · deep PostgreSQL catalogue against the simulated clinical source."""

from collections.abc import Iterator

import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.testing import assert_sql_writes_rejected
from argos_sql.postgres import PostgresConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration


@pytest.fixture
def connector(migrated_db: str) -> Iterator[PostgresConnector]:
    c = open_source_connector("dev-source-postgres", PostgresConnector, migrated_db)
    yield c
    c.close()


def test_scan_adds_size_estimates_comments_and_replica_flag(connector: PostgresConnector) -> None:
    result = connector.execute(ProbeSpec("scan_schema", "clinic"))
    patients = result.data["schemas"]["clinic"]["patients"]
    assert patients["bytes"] > 0 and patients["est_rows"] > 0
    assert "Synthetic" in patients["comment"]
    assert result.data["is_replica"] is False


def test_privileges_include_nologin_grantees_and_effective_readers(
    connector: PostgresConnector,
) -> None:
    params = {"check": "privileges", "schema": "clinic", "table": "patients"}
    result = connector.execute(ProbeSpec("check_config", "clinic.patients", params=params))
    roles = {(r["role_name"], r["privilege_type"]) for r in result.data["rows"]}
    assert ("clinic_admin", "DELETE") in roles
    assert ("argos_ro", "SELECT (effective)") in roles


def test_encryption_and_replica_checks(connector: PostgresConnector) -> None:
    encryption = connector.execute(
        ProbeSpec("check_config", "server", params={"check": "encryption_at_rest"})
    )
    assert {"ssl", "password_encryption"} <= {r["name"] for r in encryption.data["rows"]}
    assert "note" in encryption.data
    replica = connector.execute(
        ProbeSpec("check_config", "server", params={"check": "replica_status"})
    )
    assert replica.data["rows"][0]["standby"] is False


def test_write_harness(connector: PostgresConnector) -> None:
    assert_sql_writes_rejected(connector, "clinic.patients")
