"""ARG-024 · validation in origin against the simulated sources: rates only (F03-05)."""

import pytest

from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec
from argos_sql.generic import SqlConnector
from argos_sql.postgres import PostgresConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("name", "cls", "table"),
    [
        ("dev-source-postgres", PostgresConnector, "clinic.patient_documents"),
        ("dev-source-mariadb", SqlConnector, "billing.patient_mirror"),
    ],
)
def test_documents_are_formally_valid_in_origin(
    migrated_db: str, name: str, cls: type[Connector], table: str
) -> None:
    connector = open_source_connector(name, cls, migrated_db)
    try:
        params = {"columns": ["dni_number", "iban"], "k": 200, "validators": ["dni", "iban_es"]}
        result = connector.execute(ProbeSpec("sample", table, params=params))
    finally:
        connector.close()
    assert result.ok, result.data
    assert result.data["validator_rates"]["dni_number"]["dni"] == 1.0
    assert result.data["validator_rates"]["iban"]["iban_es"] == 1.0
    assert result.data["validated"] == {"dni_number": 200, "iban": 200}
    assert "9999000100" not in repr(result)


def test_synthetic_national_ids_are_not_dni(migrated_db: str) -> None:
    connector = open_source_connector("dev-source-postgres", PostgresConnector, migrated_db)
    try:
        params = {"columns": ["national_id"], "k": 100, "validators": ["dni", "nie"]}
        result = connector.execute(ProbeSpec("sample", "clinic.patients", params=params))
    finally:
        connector.close()
    assert result.data["validator_rates"] == {"national_id": {"dni": 0.0, "nie": 0.0}}
