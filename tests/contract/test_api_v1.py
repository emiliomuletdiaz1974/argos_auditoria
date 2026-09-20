"""ARG-071 · the v1 contract: what the console and the client's integration can count on.

The contract is versioned in `services/api/openapi.json` and generated from the code. These tests
read the generated document, not the file, so a route that drifts from the contract fails here and
in `tools/api_contract.py --check`, which compares both.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from argos_api.app import create_app
from argos_auth import Identity, JwtValidator

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "services" / "api" / "openapi.json"
TOOL = REPO / "tools" / "api_contract.py"
PROBLEM = "application/problem+json"

EXPECTED_ROUTES = {
    ("get", "/api/v1/systems"),
    ("get", "/api/v1/inventory/coverage"),
    ("get", "/api/v1/inventory/nodes/{node_key}"),
    ("get", "/api/v1/inventory/review-queue"),
    ("post", "/api/v1/inventory/review-queue/{node_key}"),
    ("post", "/api/v1/campaigns"),
    ("get", "/api/v1/campaigns"),
    ("get", "/api/v1/campaigns/{campaign_id}"),
    ("post", "/api/v1/campaigns/{campaign_id}/launch"),
    ("get", "/api/v1/campaigns/{campaign_id}/plan"),
    ("get", "/api/v1/campaigns/{campaign_id}/progress"),
    ("get", "/api/v1/campaigns/{campaign_id}/gates"),
    ("post", "/api/v1/campaigns/{campaign_id}/gates/{gate}/approve"),
    ("get", "/api/v1/findings"),
    ("get", "/api/v1/findings/{finding_id}"),
    ("post", "/api/v1/findings/{finding_id}/transition"),
    ("post", "/api/v1/findings/{finding_id}/verify"),
    ("get", "/api/v1/evidence/{campaign_id}/chain"),
    ("get", "/api/v1/evidence/{campaign_id}/artifacts"),
    ("get", "/api/v1/evidence/artifacts/{verdict_id}"),
    ("get", "/api/v1/evidence/{campaign_id}/dossier.json"),
    ("get", "/api/v1/evidence/{campaign_id}/dossier.pdf"),
    ("get", "/api/v1/evidence/{campaign_id}/bundle"),
    ("post", "/api/v1/credentials"),
    ("get", "/api/v1/credentials/{credential_id}"),
    ("post", "/api/v1/credentials/{credential_id}/revoke"),
    ("post", "/api/v1/assistant/ask"),
    ("get", "/api/v1/approvals"),
    ("post", "/api/v1/webhooks"),
    ("get", "/api/v1/webhooks"),
    ("get", "/api/v1/webhooks/{webhook_id}/deliveries"),
    ("post", "/api/v1/auth/refresh"),
}
LISTS = {
    "/api/v1/systems",
    "/api/v1/campaigns",
    "/api/v1/findings",
    "/api/v1/inventory/review-queue",
    "/api/v1/evidence/{campaign_id}/artifacts",
    "/api/v1/webhooks",
}
CREATORS = {"/api/v1/campaigns", "/api/v1/credentials", "/api/v1/webhooks"}
BEARER = {"Authorization": "Bearer a-token"}


class FakeValidator:
    """Accepts any token: what these tests check is the contract, not Keycloak."""

    def validate(self, token: str) -> Identity:
        return Identity(sub="dpo", name="DPO", roles=frozenset({"dpo_reviewer"}))


def _client_with_identity() -> TestClient:
    return TestClient(create_app(cast(JwtValidator, FakeValidator())))


def _generated() -> dict[str, Any]:
    document: dict[str, Any] = create_app().openapi()
    return document


def _operations(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method, path): operation
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
    }


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_contract", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_contract_declares_every_resource_of_the_domain() -> None:
    assert _operations(_generated()).keys() >= EXPECTED_ROUTES


def test_the_contract_is_only_v1_and_a_health_check() -> None:
    document = _generated()
    outside = [p for p in document["paths"] if not p.startswith("/api/v1/") and p != "/health"]
    assert outside == []
    assert document["info"]["version"] == "1"


@pytest.mark.parametrize("path", sorted(LISTS))
def test_every_listing_paginates_by_opaque_cursor(path: str) -> None:
    operation = _operations(_generated())[("get", path)]
    parameters = {p["name"] for p in operation.get("parameters", [])}
    assert {"cursor", "limit"} <= parameters, path
    assert "offset" not in parameters, path


@pytest.mark.parametrize("path", sorted(CREATORS))
def test_every_creating_post_accepts_an_idempotency_key(path: str) -> None:
    operation = _operations(_generated())[("post", path)]
    headers = {p["name"] for p in operation.get("parameters", []) if p["in"] == "header"}
    assert "Idempotency-Key" in headers, path


def test_every_route_but_health_and_refresh_answers_401_as_problem_json() -> None:
    open_routes = {("get", "/health"), ("post", "/api/v1/auth/refresh")}
    for (method, path), operation in _operations(_generated()).items():
        if (method, path) in open_routes:
            continue
        responses = operation["responses"]
        assert "401" in responses, (method, path)
        assert PROBLEM in responses["401"]["content"], (method, path)


def test_the_error_shape_is_rfc_9457() -> None:
    schema = _generated()["components"]["schemas"]["Problem"]
    assert {"type", "title", "status", "instance"} <= set(schema["properties"])


def test_an_anonymous_call_is_refused_as_a_problem() -> None:
    response = TestClient(create_app()).get("/api/v1/campaigns")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    assert body["status"] == 401
    assert body["instance"] == "/api/v1/campaigns"
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_page_larger_than_the_maximum_is_refused_as_a_problem() -> None:
    client = _client_with_identity()
    response = client.get("/api/v1/campaigns", params={"limit": 5000}, headers=BEARER)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert "limit" in response.json()["detail"]


def test_an_unknown_route_is_also_a_problem() -> None:
    response = TestClient(create_app()).get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM)


def test_the_health_check_needs_no_token() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "argos-api"


def test_the_versioned_contract_is_the_generated_one() -> None:
    assert json.loads(CONTRACT.read_text(encoding="utf-8")) == _generated()
    assert _tool().main(["--check"]) == 0
