"""ARG-014/020/024 · the connectors against the simulated sources (security review F09-02).

- SEC-054: a table whose name has capitals and a dot still has its access edges.
- SEC-028: a PACS without TLS is refused unless the system declares it.
- SEC-024: a table that fails its probe is recorded and the classification goes on.
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from argos_common.errors import ConfigurationError
from argos_connector.probes import ProbeSpec
from argos_dicom.connector import DicomConnector
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_sql.postgres import PostgresConnector

from .inventory_helpers import probe_runner, scan_and_ingest
from .sources import open_source_connector

pytestmark = pytest.mark.integration

CLINIC_OWNER = "postgresql://owner@127.0.0.1:55433/clinic"
SCHEMA = "argos_names_probe"


@pytest.fixture
def odd_table() -> Iterator[None]:
    with psycopg.connect(CLINIC_OWNER, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(f'CREATE TABLE {SCHEMA}."Pacientes.2024" (id integer)')
    try:
        yield
    finally:
        with psycopg.connect(CLINIC_OWNER, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


def test_a_table_with_capitals_and_a_dot_has_its_access_edges(
    migrated_db: str, odd_table: None
) -> None:
    connector = open_source_connector("dev-source-postgres", PostgresConnector, migrated_db)
    try:
        result = connector.execute(
            ProbeSpec(
                "check_config",
                f"{SCHEMA}.Pacientes.2024",
                params={"check": "privileges", "schema": SCHEMA, "table": "Pacientes.2024"},
            )
        )
    finally:
        connector.close()
    assert result.ok
    assert {"role_name": "owner", "privilege_type": "SELECT (effective)"} in result.data["rows"]


def test_a_pacs_without_tls_is_refused_unless_the_system_declares_it(migrated_db: str) -> None:
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        open_source_connector(
            "dev-clinical-dicom", DicomConnector, migrated_db, config={"ae_title": "ARGOS_QR"}
        )
    declared = open_source_connector("dev-clinical-dicom", DicomConnector, migrated_db)
    declared.close()


def test_a_table_that_fails_does_not_stop_the_classification(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    runner = probe_runner(migrated_db)
    failed: list[str] = []
    sampled: list[str] = []

    def breaking(system: str, spec: ProbeSpec) -> Any:
        if not failed:
            failed.append(spec.target)
            raise ValueError(f"invalid SQL identifier: {spec.target!r}")
        sampled.append(spec.target)
        return runner(system, spec)

    summary = classify_new_columns(GraphStore(migrated_db), breaking, system_id)
    # The failure is counted, not raised: the phase ends with what it classified by name.
    assert failed and summary.probe_failures == 1
    assert summary.dictionary > 0
    assert failed[0] not in sampled
