"""Translate read-only probe results into DISCOVERY events (ARG-022, deviation note ARG-021-023).

Connectors never publish: the scanner runs their probes and turns each minimised result into facts
the ingest can materialise. Events carry provenance and never a sampled value.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from argos_connector.probes import ProbeResult

from .probes import RegisteredSystem

SUBJECT_PREFIX = "argos.discovery."
DIRECTORY_FIELDS = ("users", "disabled", "password_never_expires", "service_like", "groups")


class EventPublisher(Protocol):
    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class DiscoveryEvent:
    name: str
    data: dict[str, Any]

    @property
    def subject(self) -> str:
        return f"{SUBJECT_PREFIX}{self.name}"

    @property
    def event_type(self) -> str:
        return f"discovery.{self.name}.v1"


def discovery_target(system: RegisteredSystem) -> str:
    if system.kind == "files":
        return ""
    if system.kind == "directory":
        return str(system.config["base_dn"])
    return "*"


def provenance(
    system: RegisteredSystem, result: ProbeResult, run_id: str, observed_at: str
) -> dict[str, Any]:
    return {
        "system_id": system.id,
        "run_id": run_id,
        "source_connector": system.connector,
        "probe_id": result.probe_id,
        "journal_seq": result.journal_seq,
        "observed_at": observed_at,
    }


def _table_events(
    system: RegisteredSystem, result: ProbeResult, run_id: str, observed_at: str
) -> list[DiscoveryEvent]:
    base = provenance(system, result, run_id, observed_at)
    events: list[DiscoveryEvent] = []
    for schema, tables in sorted(result.data.get("schemas", {}).items()):
        for table, detail in sorted(tables.items()):
            columns = [
                {"name": str(c["name"]), "type": str(c["type"]), "nullable": bool(c["nullable"])}
                for c in detail.get("columns", [])
            ]
            data = {
                **base,
                "schema": str(schema),
                "table": str(table),
                "est_rows": int(detail.get("est_rows", -1)),
                "bytes": int(detail.get("bytes", -1)),
                "comment": detail.get("comment"),
                "columns": columns,
            }
            events.append(DiscoveryEvent("table_found", data))
    return events


def _summary_event(
    system: RegisteredSystem, result: ProbeResult, run_id: str, observed_at: str
) -> DiscoveryEvent:
    base = provenance(system, result, run_id, observed_at)
    data = result.data
    if system.kind == "files":
        area = {
            "path": "",
            "total": int(data["total"]),
            "bytes": int(data["bytes"]),
            "by_ext": {str(k): int(v) for k, v in data["by_ext"].items()},
            "age_years": {str(k): int(v) for k, v in data["age_years"].items()},
            "capped": bool(data["capped"]),
        }
        return DiscoveryEvent("file_area_scanned", {**base, **area})
    if system.kind == "directory":
        summary = {k: int(data[k]) for k in DIRECTORY_FIELDS}
        return DiscoveryEvent("directory_summarized", {**base, **summary})
    if system.kind == "api":
        routes = [
            {
                "path": str(r["path"]),
                "status": int(r["status"]),
                "content_type": r.get("content_type"),
            }
            for r in data["routes"]
        ]
        return DiscoveryEvent("api_routes_found", {**base, "routes": routes})
    if system.kind == "clinical" and "fhir_version" in data:
        fhir = {
            "standard": "fhir",
            "fhir_version": data["fhir_version"],
            "resources": sorted(str(r) for r in data["resources"]),
            "sensitive_present": [str(r) for r in data["sensitive_present"]],
        }
        return DiscoveryEvent("clinical_resources_found", {**base, **fhir})
    if system.kind == "clinical":
        dicom = {
            "standard": "dicom",
            "studies": int(data["studies"]),
            "by_modality": {str(k): int(v) for k, v in data["by_modality"].items()},
            "capped": bool(data["capped"]),
        }
        return DiscoveryEvent("clinical_resources_found", {**base, **dicom})
    raise ValueError(f"no discovery summary for system kind {system.kind!r}")


def events_for(
    system: RegisteredSystem, result: ProbeResult, run_id: str, observed_at: str
) -> list[DiscoveryEvent]:
    if system.kind == "rdbms":
        return _table_events(system, result, run_id, observed_at)
    return [_summary_event(system, result, run_id, observed_at)]


def access_event(
    system: RegisteredSystem,
    result: ProbeResult,
    run_id: str,
    observed_at: str,
    schema: str,
    table: str,
) -> DiscoveryEvent:
    pairs = sorted({(str(r["role_name"]), str(r["privilege_type"])) for r in result.data["rows"]})
    grants = [{"grantee": grantee, "privilege": privilege} for grantee, privilege in pairs]
    data = {
        **provenance(system, result, run_id, observed_at),
        "schema": schema,
        "table": table,
        "grants": grants,
    }
    return DiscoveryEvent("access_found", data)


def scan_completed_event(
    system_id: str,
    run_id: str,
    status: str,
    started_at: str,
    finished_at: str,
    events: int,
    failed_probes: int,
    error: str | None,
) -> DiscoveryEvent:
    data = {
        "system_id": system_id,
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "events": events,
        "failed_probes": failed_probes,
        "error": error,
    }
    return DiscoveryEvent("scan_completed", data)
