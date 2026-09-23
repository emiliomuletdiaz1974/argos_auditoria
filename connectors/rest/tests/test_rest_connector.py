"""Declarative REST connector (ARG-019): exact allowlist, safe methods, confined pagination."""

import json
from typing import Any

import httpx
import pytest

from argos_common.errors import ConfigurationError, ReadOnlyViolationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import (
    InMemoryJournal,
    assert_http_writes_rejected,
    assert_no_write_surface,
    make_context,
)
from argos_rest.connector import DEFAULT_MAX_PAGES, RestConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
DESCRIPTOR: dict[str, Any] = {
    "base_url": "https://api.hospital.test/v1",
    "routes": [
        {
            "path": "/patients",
            "items_field": "items",
            "page": {"param": "cursor", "next_field": "next_cursor"},
        },
        {"path": "/patients/{id}", "defaults": {"id": "1"}},
        {"path": "/stats/patients", "count_field": "summary.total"},
        {"path": "/documents", "items_field": "data", "page": {"next_field": "links.next"}},
        {"path": "/redirecting"},
    ],
}
HSTS = {"strict-transport-security": "max-age=63072000"}
TEST_TOKEN = "t-123"


class Api:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.foreign_next = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, params = request.url.path, dict(request.url.params)
        if path == "/v1/patients":
            cursor = int(params.get("cursor", "0"))
            items = [
                {"id": cursor + i, "profile": {"national_id": f"SYN{cursor + i:08d}"}}
                for i in range(2)
            ]
            following = str(cursor + 2) if cursor < 4 else None
            body: dict[str, Any] = {"items": items, "next_cursor": following}
            return httpx.Response(200, json=body, headers=HSTS)
        if path == "/v1/stats/patients":
            return httpx.Response(200, json={"summary": {"total": 1234}})
        if path == "/v1/documents":
            page = int(params.get("page", "1"))
            origin = "https://evil.test" if self.foreign_next else "https://api.hospital.test"
            link = f"{origin}/v1/documents?page={page + 1}" if page < 3 else None
            return httpx.Response(200, json={"data": [{"id": page}], "links": {"next": link}})
        if path == "/v1/redirecting":
            return httpx.Response(302, headers={"location": "https://evil.test/steal"})
        return httpx.Response(200, json={})


def test_a_clear_http_api_is_refused_unless_declared() -> None:
    # The bearer token would travel in clear text.
    descriptor = {**DESCRIPTOR, "base_url": "http://api.hospital.test/v1"}
    context = make_context({"token": TEST_TOKEN})
    connector = RestConnector(SYSTEM_ID, {"descriptor": descriptor}, context)
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        connector.open()
    declared = {"descriptor": descriptor, "allow_insecure": True}
    allowed = RestConnector(SYSTEM_ID, declared, make_context({"token": TEST_TOKEN}))
    allowed.open()
    allowed.close()


class MockRest(RestConnector):
    api: Api

    def _client_options(self) -> dict[str, Any]:
        return {"transport": httpx.MockTransport(self.api)}


def _connector() -> tuple[MockRest, Api, InMemoryJournal]:
    api, journal = Api(), InMemoryJournal()
    credentials = {"token": TEST_TOKEN}
    context = make_context(credentials, journal=journal)
    connector = MockRest(SYSTEM_ID, {"descriptor": DESCRIPTOR}, context)
    connector.api = api
    connector.open()
    return connector, api, journal


def test_write_methods_are_rejected_before_any_request() -> None:
    connector, api, _ = _connector()
    assert_http_writes_rejected(lambda method, path: connector._request(method, path), "/patients")
    assert api.requests == []


@pytest.mark.parametrize(
    "path",
    [
        "/patients-export",
        "/patients/1/../../admin",
        "/admin",
        "https://evil.test/patients",
        "//evil.test/patients",
        "/patients%2F..%2Fadmin",
        "/patients/1/extra",
        "patients",
    ],
)
def test_paths_outside_the_exact_allowlist_are_journaled_rejections(path: str) -> None:
    connector, api, journal = _connector()
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("count", path))
    assert api.requests == [] and len(journal.rejected) == 1


def test_count_from_a_count_field() -> None:
    connector, _, journal = _connector()
    result = connector.execute(ProbeSpec("count", "/stats/patients"))
    assert result.data == {"count": 1234, "capped": False, "pages": 1}
    assert journal.emitted[0].spec.statement == "GET /stats/patients"


def test_count_by_cursor_pagination_with_bearer_token() -> None:
    connector, api, _ = _connector()
    spec = ProbeSpec("count", "/patients", params={"query": {"active": "true"}})
    result = connector.execute(spec)
    assert result.data == {"count": 6, "capped": False, "pages": 3}
    assert [r.url.params.get("cursor") for r in api.requests] == [None, "2", "4"]
    assert all(r.headers["authorization"] == "Bearer t-123" for r in api.requests)


def test_count_is_capped() -> None:
    connector, _, _ = _connector()
    result = connector.execute(ProbeSpec("count", "/patients", params={"cap": 3}))
    assert result.data["capped"] is True


def test_one_probe_cannot_page_the_api_without_end() -> None:
    # A probe takes one permit from the load budget: its pages are bounded, not unlimited.
    connector, api, _ = _connector()
    connector.config["max_pages"] = 2
    result = connector.execute(ProbeSpec("count", "/patients"))
    assert result.data == {"count": 4, "capped": True, "pages": 2}
    assert len(api.requests) == 2
    assert DEFAULT_MAX_PAGES == 100


def test_link_pagination_stays_on_the_base_origin() -> None:
    connector, api, _ = _connector()
    assert connector.execute(ProbeSpec("count", "/documents")).data["count"] == 3
    api.foreign_next = True
    with pytest.raises(ReadOnlyViolationError, match="origin"):
        connector.execute(ProbeSpec("count", "/documents"))
    assert [r.url.host for r in api.requests].count("evil.test") == 0


def test_sample_hashes_dotted_fields_only() -> None:
    connector, _, _ = _connector()
    params = {"fields": ["profile.national_id"], "k": 2}
    result = connector.execute(ProbeSpec("sample", "/patients", params=params))
    assert result.data["n"] == 2 and len(result.data["rows"][0]["profile.national_id"]) == 32
    assert "SYN" not in repr(result)


def test_scan_heads_every_route_with_its_defaults() -> None:
    connector, api, journal = _connector()
    result = connector.execute(ProbeSpec("scan_schema", "*"))
    assert [r["path"] for r in result.data["routes"]] == [r["path"] for r in DESCRIPTOR["routes"]]
    assert {r.method for r in api.requests} == {"HEAD"}
    assert "HEAD /patients/1" in (journal.emitted[0].spec.statement or "")


def test_check_config_reports_security_headers_and_never_follows_redirects() -> None:
    connector, api, _ = _connector()
    headers = connector.execute(ProbeSpec("check_config", "/patients"))
    assert headers.data["security_headers"]["strict-transport-security"] == "max-age=63072000"
    redirect = connector.execute(ProbeSpec("check_config", "/redirecting"))
    assert redirect.data["status"] == 302
    assert [r.url.host for r in api.requests].count("evil.test") == 0


@pytest.mark.parametrize("template", ["/a/../b", "relative", "/a/{bad name}"])
def test_invalid_route_templates_are_refused_at_open(template: str) -> None:
    descriptor = {"base_url": "https://x.test", "routes": [{"path": template}]}
    connector = MockRest(SYSTEM_ID, {"descriptor": descriptor}, make_context())
    connector.api = Api()
    with pytest.raises(ValueError, match="route template"):
        connector.open()


def test_no_write_surface() -> None:
    assert_no_write_surface(RestConnector)


def test_journaled_statement_includes_the_sorted_query() -> None:
    connector, _, journal = _connector()
    params = {"fields": ["id"], "query": {"b": "2", "a": "1"}}
    connector.execute(ProbeSpec("sample", "/patients", params=params))
    assert journal.emitted[0].spec.statement == "GET /patients?a=1&b=2"
    assert json.dumps(journal.emitted[0].spec.params)  # params stay JSON-serialisable


def test_every_page_beyond_the_first_is_paid_and_journaled() -> None:
    """SEC-023: pages the server hands out are requests to the customer system like any other."""
    connector, api, journal = _connector()
    result = connector.execute(ProbeSpec("count", "/patients"))
    assert result.data["pages"] == 3 and len(api.requests) == 3
    budget: Any = connector.context.budget
    assert budget.acquired == 3
    assert len(journal.emitted) == 3
    assert all(r.outcome is not None and r.outcome["ok"] for r in journal.emitted)
