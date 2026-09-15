"""ARG-022 · probe results become DISCOVERY events with provenance and no sampled values."""

from typing import Any

import pytest

from argos_connector.probes import ProbeResult
from argos_inventory.discovery.events import (
    access_event,
    discovery_target,
    events_for,
    scan_completed_event,
)
from argos_inventory.discovery.probes import RegisteredSystem, connector_class
from argos_sql.postgres import PostgresConnector

SYSTEM_ID = "01920000-0000-7000-8000-00000000a001"
RUN = "0192a000-0000-7000-8000-000000000001"
AT = "2026-09-15T10:00:00+00:00"
PROVENANCE = ("system_id", "run_id", "source_connector", "probe_id", "journal_seq", "observed_at")


def _system(kind: str, connector: str, **config: Any) -> RegisteredSystem:
    return RegisteredSystem(SYSTEM_ID, f"dev-{kind}", kind, connector, dict(config))


def _result(data: dict[str, Any], kind: str = "scan_schema") -> ProbeResult:
    return ProbeResult("probe-1", kind, True, data, 12, 3, 41)


def test_tables_carry_their_columns_and_provenance() -> None:
    system = _system("rdbms", "argos_sql.postgres:PostgresConnector")
    detail = {
        "columns": [{"name": "national_id", "type": "TEXT", "nullable": False}],
        "bytes": 8192,
        "est_rows": 5000,
        "comment": "Synthetic patients",
    }
    data = {"schemas": {"clinic": {"patients": detail}}, "is_replica": False}
    [event] = events_for(system, _result(data), RUN, AT)
    assert event.subject == "argos.discovery.table_found"
    assert event.event_type == "discovery.table_found.v1"
    assert event.data["columns"] == [{"name": "national_id", "type": "TEXT", "nullable": False}]
    assert (event.data["schema"], event.data["table"], event.data["est_rows"]) == (
        "clinic",
        "patients",
        5000,
    )
    assert {k: event.data[k] for k in PROVENANCE} == {
        "system_id": SYSTEM_ID,
        "run_id": RUN,
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": "probe-1",
        "journal_seq": 41,
        "observed_at": AT,
    }


def test_generic_sql_tables_without_estimates_use_minus_one() -> None:
    system = _system("rdbms", "argos_sql.generic:SqlConnector")
    columns = [{"name": "status", "type": "VARCHAR(12)", "nullable": False}]
    data = {"schemas": {"billing": {"invoices": {"columns": columns}}}}
    [event] = events_for(system, _result(data), RUN, AT)
    assert (event.data["est_rows"], event.data["bytes"], event.data["comment"]) == (-1, -1, None)


def test_access_event_sorts_and_deduplicates_grants() -> None:
    system = _system("rdbms", "argos_sql.postgres:PostgresConnector")
    rows = [
        {"role_name": "clinic_admin", "privilege_type": "DELETE"},
        {"role_name": "argos_ro", "privilege_type": "SELECT (effective)"},
        {"role_name": "clinic_admin", "privilege_type": "DELETE"},
    ]
    result = _result({"rows": rows}, "check_config")
    event = access_event(system, result, RUN, AT, "clinic", "patients")
    assert event.event_type == "discovery.access_found.v1"
    assert event.data["grants"] == [
        {"grantee": "argos_ro", "privilege": "SELECT (effective)"},
        {"grantee": "clinic_admin", "privilege": "DELETE"},
    ]


@pytest.mark.parametrize(
    ("kind", "connector", "data", "name"),
    [
        (
            "files",
            "argos_files.connector:FilesConnector",
            {
                "total": 121,
                "bytes": 9000,
                "by_ext": {"onnx": 1},
                "age_years": {"0": 10},
                "capped": False,
            },
            "file_area_scanned",
        ),
        (
            "directory",
            "argos_ldap.connector:LdapConnector",
            {
                "users": 301,
                "disabled": 0,
                "password_never_expires": 0,
                "service_like": 0,
                "groups": 3,
            },
            "directory_summarized",
        ),
        (
            "api",
            "argos_rest.connector:RestConnector",
            {"routes": [{"path": "/realms/{realm}", "status": 405, "content_type": None}]},
            "api_routes_found",
        ),
        (
            "clinical",
            "argos_fhir.connector:FhirConnector",
            {"fhir_version": "4.0.1", "resources": ["Patient"], "sensitive_present": ["Patient"]},
            "clinical_resources_found",
        ),
        (
            "clinical",
            "argos_dicom.connector:DicomConnector",
            {"studies": 40, "by_modality": {"CT": 14}, "capped": False},
            "clinical_resources_found",
        ),
    ],
)
def test_one_summary_event_per_non_relational_system(
    kind: str, connector: str, data: dict[str, Any], name: str
) -> None:
    system = _system(kind, connector, base_dn="dc=hosp,dc=local")
    [event] = events_for(system, _result(data), RUN, AT)
    assert event.subject == f"argos.discovery.{name}"
    assert event.data["probe_id"] == "probe-1" and event.data["journal_seq"] == 41


def test_clinical_events_name_their_standard() -> None:
    fhir = _system("clinical", "argos_fhir.connector:FhirConnector")
    dicom = _system("clinical", "argos_dicom.connector:DicomConnector")
    fhir_data = {"fhir_version": "4.0.1", "resources": ["Patient"], "sensitive_present": []}
    dicom_data = {"studies": 1, "by_modality": {"MR": 1}, "capped": False}
    assert events_for(fhir, _result(fhir_data), RUN, AT)[0].data["standard"] == "fhir"
    assert events_for(dicom, _result(dicom_data), RUN, AT)[0].data["standard"] == "dicom"


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="kind"):
        events_for(_system("ai", "argos_sql.generic:SqlConnector"), _result({}), RUN, AT)


def test_discovery_targets() -> None:
    assert discovery_target(_system("files", "x:y")) == ""
    directory = _system("directory", "x:y", base_dn="dc=hosp,dc=local")
    assert discovery_target(directory) == "dc=hosp,dc=local"
    assert {discovery_target(_system(k, "x:y")) for k in ("rdbms", "api", "clinical")} == {"*"}


def test_scan_completed_event_summarises_the_run() -> None:
    event = scan_completed_event(SYSTEM_ID, RUN, "failed", AT, AT, 0, 1, "ValueError")
    assert event.event_type == "discovery.scan_completed.v1"
    assert event.data == {
        "system_id": SYSTEM_ID,
        "run_id": RUN,
        "status": "failed",
        "started_at": AT,
        "finished_at": AT,
        "events": 0,
        "failed_probes": 1,
        "error": "ValueError",
    }


@pytest.mark.parametrize(
    "path",
    [
        "os:system",
        "argos_sql.generic",
        "argos_sql.generic:ConfigCheck",
        "argos_sqlx.evil:Connector",
    ],
)
def test_only_argos_connector_classes_can_be_loaded(path: str) -> None:
    with pytest.raises(ValueError, match="connector"):
        connector_class(path)


def test_connector_class_resolves_a_registered_connector() -> None:
    assert connector_class("argos_sql.postgres:PostgresConnector") is PostgresConnector
