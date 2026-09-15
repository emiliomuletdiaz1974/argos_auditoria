"""ARG-022 · ingest parameters: natural keys, qualified names and provenance, without I/O."""

from typing import Any

import pytest

from argos_inventory.discovery.events import DiscoveryEvent
from argos_inventory.graph.model import (
    column_key,
    file_area_key,
    identity_key,
    schema_key,
    system_key,
    table_key,
)
from argos_inventory.ingest.handlers import HANDLERS, SystemMeta
from argos_inventory.ingest.parameters import (
    access_parameters,
    file_area_parameters,
    summary_parameters,
    system_parameters,
    table_parameters,
)

SID = "01920000-0000-7000-8000-00000000a001"
AT = "2026-09-15T10:00:00+00:00"
PROVENANCE: dict[str, Any] = {
    "system_id": SID,
    "run_id": "0192a000-0000-7000-8000-000000000001",
    "source_connector": "argos_sql.postgres:PostgresConnector",
    "probe_id": "probe-1",
    "journal_seq": 41,
    "observed_at": AT,
}


def test_system_parameters_come_from_the_catalog() -> None:
    meta = SystemMeta(SID, "dev-source-postgres", "rdbms", None)
    assert system_parameters(meta, AT) == {
        "system_key": system_key(SID),
        "system_id": SID,
        "name": "dev-source-postgres",
        "kind": "rdbms",
        "owner": None,
        "at": AT,
    }


def test_table_parameters_carry_keys_and_qualified_names() -> None:
    data = {
        **PROVENANCE,
        "schema": "clinic",
        "table": "patients",
        "est_rows": 5000,
        "bytes": 8192,
        "comment": "Synthetic patients",
        "columns": [{"name": "national_id", "type": "TEXT", "nullable": False}],
    }
    params = table_parameters(data)
    assert params["schema_key"] == schema_key(SID, "clinic")
    assert params["table_key"] == table_key(SID, "clinic", "patients")
    assert params["qualified_name"] == "clinic.patients"
    assert params["columns"] == [
        {
            "key": column_key(SID, "clinic", "patients", "national_id"),
            "name": "national_id",
            "qualified_name": "clinic.patients.national_id",
            "type": "TEXT",
            "nullable": False,
        }
    ]
    assert (params["probe_id"], params["journal_seq"], params["at"]) == ("probe-1", 41, AT)


def test_access_parameters_group_privileges_per_grantee() -> None:
    grants = [
        {"grantee": "clinic_admin", "privilege": "DELETE"},
        {"grantee": "argos_ro", "privilege": "SELECT (effective)"},
        {"grantee": "clinic_admin", "privilege": "SELECT"},
    ]
    data = {**PROVENANCE, "schema": "clinic", "table": "patients", "grants": grants}
    params = access_parameters(data)
    assert params["table_key"] == table_key(SID, "clinic", "patients")
    assert params["grants"] == [
        {
            "key": identity_key(SID, "argos_ro"),
            "grantee": "argos_ro",
            "privileges": ["SELECT (effective)"],
        },
        {
            "key": identity_key(SID, "clinic_admin"),
            "grantee": "clinic_admin",
            "privileges": ["DELETE", "SELECT"],
        },
    ]


def test_file_area_parameters_name_the_root_area() -> None:
    data = {
        **PROVENANCE,
        "path": "",
        "total": 121,
        "bytes": 9000,
        "by_ext": {"onnx": 1},
        "age_years": {"0": 121},
        "capped": False,
    }
    params = file_area_parameters(data)
    assert params["area_key"] == file_area_key(SID, "")
    assert (params["name"], params["total"], params["by_ext"]) == ("/", 121, {"onnx": 1})


@pytest.mark.parametrize(
    ("event_type", "fields", "routes"),
    [
        ("discovery.directory_summarized.v1", {"users": 301, "groups": 3}, []),
        (
            "discovery.api_routes_found.v1",
            {"routes": [{"path": "/realms/{realm}", "status": 405, "content_type": None}]},
            ["/realms/{realm}"],
        ),
        (
            "discovery.clinical_resources_found.v1",
            {"standard": "dicom", "studies": 40, "by_modality": {"CT": 14}, "capped": False},
            [],
        ),
    ],
)
def test_summary_parameters_drop_provenance_from_the_summary(
    event_type: str, fields: dict[str, Any], routes: list[str]
) -> None:
    params = summary_parameters(event_type, {**PROVENANCE, **fields})
    assert params["system_key"] == system_key(SID)
    assert params["summary"] == fields and params["routes"] == routes
    assert params["summary_kind"] == event_type.split(".")[1]


def test_every_discovery_event_of_the_scanner_has_a_handler() -> None:
    names = [
        "table_found",
        "access_found",
        "file_area_scanned",
        "directory_summarized",
        "api_routes_found",
        "clinical_resources_found",
        "scan_completed",
    ]
    assert {DiscoveryEvent(n, {}).event_type for n in names} == set(HANDLERS)
