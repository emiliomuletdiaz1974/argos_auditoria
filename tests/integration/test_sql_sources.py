"""ARG-014 · generic SQL connector against the simulated PostgreSQL and MariaDB sources."""

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from argos_connector.probes import ProbeSpec
from argos_connector.testing import SQL_WRITE_ATTEMPTS, assert_sql_writes_rejected
from argos_sql.generic import SqlConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration

SOURCES = [
    pytest.param(
        "dev-source-postgres",
        "clinic.patients",
        "national_id",
        "birth_date < :cutoff",
        "INSERT INTO clinic.consents VALUES (1, 'x', true, now())",
        id="postgres",
    ),
    pytest.param(
        "dev-source-mariadb",
        "billing.invoices",
        "patient_ref",
        "issued_at < :cutoff",
        "INSERT INTO billing.invoices VALUES (999999, 'X', 1, NOW(), 'paid')",
        id="mariadb",
    ),
]


@pytest.mark.parametrize(("name", "target", "column", "where", "write"), SOURCES)
def test_reads_through_the_contract_and_never_writes(
    migrated_db: str, name: str, target: str, column: str, where: str, write: str
) -> None:
    connector = open_source_connector(name, SqlConnector, migrated_db)
    try:
        schema, table = target.split(".")
        scan = connector.execute(ProbeSpec("scan_schema", schema))
        assert scan.ok and table in scan.data["schemas"][schema]

        count = connector.execute(
            ProbeSpec("count", target, params={"where": where, "binds": {"cutoff": "2015-01-01"}})
        )
        assert count.ok and count.data["count"] > 0

        sample = connector.execute(
            ProbeSpec("sample", target, params={"columns": [column], "k": 20})
        )
        assert sample.ok and sample.data["n"] == 20 and "SYN" not in repr(sample)

        assert_sql_writes_rejected(connector, target)

        with connector.engine.connect() as conn, pytest.raises(DBAPIError):
            conn.execute(text(write))
            conn.commit()
    finally:
        connector.close()

    with psycopg.connect(migrated_db) as conn:
        statuses = dict(
            conn.execute(
                "SELECT status, count(*) FROM argos.connector_queries "
                "WHERE system_id = %s GROUP BY status",
                (connector.system_id,),
            ).fetchall()
        )
    assert statuses == {"completed": 3, "rejected": len(SQL_WRITE_ATTEMPTS)}
