"""FHIR connector (ARG-020): capability scan, _summary=count and closed resource routes."""

from typing import Any

import httpx
import pytest

from argos_common.errors import ReadOnlyViolationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import (
    InMemoryJournal,
    assert_http_writes_rejected,
    assert_no_write_surface,
    make_context,
)
from argos_fhir.connector import FhirConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
BASE_URL = "https://fhir.hospital.test/fhir"
DECLARED = ("Patient", "Observation", "Condition", "Consent", "Organization")


class Server:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, params = request.url.path, dict(request.url.params)
        if path == "/fhir/metadata":
            resources = [{"type": t} for t in DECLARED]
            body = {"fhirVersion": "4.0.1", "rest": [{"resource": resources}]}
            return httpx.Response(200, json=body)
        if path == "/fhir/Patient" and params.get("_summary") == "count":
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 200})
        if path == "/fhir/Patient":
            entries = [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": str(i),
                        "gender": "female",
                        "identifier": [{"value": f"SYN{i}"}],
                    }
                }
                for i in range(3)
            ]
            return httpx.Response(200, json={"resourceType": "Bundle", "entry": entries})
        return httpx.Response(404, json={})


class MockFhir(FhirConnector):
    server: Server

    def _client_options(self) -> dict[str, Any]:
        return {"transport": httpx.MockTransport(self.server)}


def _connector(**config: Any) -> tuple[MockFhir, Server, InMemoryJournal]:
    server, journal = Server(), InMemoryJournal()
    context = make_context({"base_url": BASE_URL}, journal=journal)
    connector = MockFhir(SYSTEM_ID, config, context)
    connector.server = server
    connector.open()
    return connector, server, journal


def test_scan_reads_the_capability_statement() -> None:
    connector, _, journal = _connector()
    result = connector.execute(ProbeSpec("scan_schema", "*"))
    assert result.data["fhir_version"] == "4.0.1"
    assert result.data["sensitive_present"] == ["Patient", "Condition", "Observation", "Consent"]
    assert journal.emitted[0].spec.statement == "GET /metadata"


def test_count_always_uses_summary_count() -> None:
    connector, server, journal = _connector()
    spec = ProbeSpec("count", "/Patient", params={"query": {"gender": "female"}})
    result = connector.execute(spec)
    assert result.data["count"] == 200
    assert server.requests[-1].url.params["_summary"] == "count"
    assert journal.emitted[0].spec.statement == "GET /Patient?_summary=count&gender=female"


def test_every_request_bypasses_the_server_search_cache() -> None:
    # Servers such as HAPI reuse a search result for about a minute; evidence must be fresh.
    connector, server, _ = _connector()
    connector.execute(ProbeSpec("count", "/Patient"))
    assert server.requests[-1].headers["cache-control"] == "no-cache"


def test_sample_hashes_nested_entry_fields() -> None:
    connector, server, _ = _connector()
    params = {"fields": ["resource.gender", "resource.identifier.0.value"], "k": 2}
    result = connector.execute(ProbeSpec("sample", "/Patient", params=params))
    assert result.data["n"] == 2 and server.requests[-1].url.params["_count"] == "2"
    assert "SYN" not in repr(result)


@pytest.mark.parametrize(
    "path",
    ["/Patient/$everything", "/$export", "/_history", "/Patient/1/_history", "/Organization"],
)
def test_operations_and_undeclared_resources_are_rejected(path: str) -> None:
    connector, server, journal = _connector()
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("count", path))
    assert server.requests == [] and len(journal.rejected) == 1


def test_writes_are_rejected() -> None:
    connector, server, _ = _connector()
    assert_http_writes_rejected(lambda method, path: connector._request(method, path), "/Patient")
    assert server.requests == []


def test_extra_resources_are_validated() -> None:
    connector, _, _ = _connector(extra_resources=["Organization"])
    assert connector.execute(ProbeSpec("check_config", "/Organization")).ok
    with pytest.raises(ValueError, match="resource type"):
        _connector(extra_resources=["Patient/../$export"])


def test_no_write_surface() -> None:
    assert_no_write_surface(FhirConnector)
