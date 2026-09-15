"""ARG-016 · Oracle and SQL Server connectors against the heavy simulated sources."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from argos_connector.probes import ProbeSpec
from argos_connector.testing import assert_sql_writes_rejected
from argos_sql.mssql import MssqlConnector
from argos_sql.oracle import OracleConnector

from .sources import open_source_connector

pytestmark = [pytest.mark.integration, pytest.mark.heavy]

SESSION_ISOLATION_SQL = (
    "SELECT transaction_isolation_level FROM sys.dm_exec_sessions WHERE session_id = @@SPID"
)


def _check(check: str, target: str = "server") -> ProbeSpec:
    return ProbeSpec("check_config", target, params={"check": check})


def test_oracle_catalog_checks_and_read_only_transactions(migrated_db: str) -> None:
    connector = open_source_connector("dev-source-oracle", OracleConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", "*"))
        assert "ENCOUNTERS" in scan.data["schemas"]["HIS_OWNER"]
        for check in ("audit_status", "generic_accounts", "privileged_grants"):
            assert connector.execute(_check(check, "db")).ok
        count = connector.execute(ProbeSpec("count", "HIS_OWNER.ENCOUNTERS"))
        assert count.data["count"] >= 2000
        assert_sql_writes_rejected(connector, "HIS_OWNER.ENCOUNTERS")
        with connector.engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM his_owner.encounters"))
    finally:
        connector.close()


def test_mssql_catalog_checks_and_snapshot_isolation(migrated_db: str) -> None:
    connector = open_source_connector("dev-source-mssql", MssqlConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", "*", params={"schemas": ["dbo"]}))
        assert "staff" in scan.data["schemas"]["dbo"]
        audits = connector.execute(_check("audit_status"))
        assert any(r["name"] == "argos_dev_audit" for r in audits.data["rows"])
        for check in ("generic_accounts", "privileged_grants"):
            assert connector.execute(_check(check)).ok
        assert_sql_writes_rejected(connector, "dbo.staff")
        with connector.engine.connect() as conn:
            assert conn.execute(text(SESSION_ISOLATION_SQL)).scalar_one() == 5  # SNAPSHOT
            with pytest.raises(DBAPIError):
                conn.execute(text("DELETE FROM dbo.staff"))
                conn.commit()
    finally:
        connector.close()
