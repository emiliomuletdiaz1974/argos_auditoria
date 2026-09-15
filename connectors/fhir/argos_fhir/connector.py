"""FHIR connector: the clinical REST path, with minimum-cost counts (ARG-020)."""

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from argos_connector.probes import ProbeSpec
from argos_rest.connector import RestConnector

SENSITIVE_RESOURCES = (
    "Patient",
    "Condition",
    "Observation",
    "DocumentReference",
    "Consent",
    "AuditEvent",
)
_RESOURCE_TYPE = re.compile(r"^[A-Z][A-Za-z]+$")


class FhirConnector(RestConnector):
    kind = "clinical.fhir"

    def _descriptor(self) -> Mapping[str, Any]:
        extra = [str(r) for r in self.config.get("extra_resources", [])]
        for resource in extra:
            if not _RESOURCE_TYPE.match(resource):
                raise ValueError(f"invalid FHIR resource type: {resource!r}")
        routes: list[dict[str, Any]] = [{"path": "/metadata", "items_field": "rest"}]
        routes += [
            {"path": f"/{resource}", "items_field": "entry", "count_field": "total"}
            for resource in (*SENSITIVE_RESOURCES, *extra)
        ]
        return {"base_url": self.context.credentials["base_url"], "routes": routes}

    def open(self) -> None:
        super().open()
        # Servers such as HAPI reuse a search result for about a minute, _summary=count included:
        # a count taken right after a change would be stale evidence. A header, not a write.
        self.client.headers["Cache-Control"] = "no-cache"

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "scan_schema":
            self.route_for("/metadata")
            return replace(spec, statement="GET /metadata")
        query = dict(spec.params.get("query", {}))
        if spec.kind == "count":
            query["_summary"] = "count"
        elif spec.kind == "sample":
            limit = min(int(spec.params.get("k", 50)), self.context.budget.max_rows_per_probe)
            query["_count"] = str(limit)
        return super().render(replace(spec, params={**spec.params, "query": query}))

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        capability = self._json("/metadata")
        resources = sorted(
            {
                str(r["type"])
                for rest in capability.get("rest", [])
                for r in rest.get("resource", [])
            }
        )
        data = {
            "fhir_version": capability.get("fhirVersion"),
            "resources": resources,
            "sensitive_present": [r for r in SENSITIVE_RESOURCES if r in resources],
        }
        return data, len(resources)
