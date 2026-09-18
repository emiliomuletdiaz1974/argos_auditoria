"""ARG-052 · the gateway as a service: the internal door other services knock on (F06-13).

Two endpoints, as the phase document designs them: `/health` and `/v1/chat_json`. It is internal:
reachable only on the network of the AI layer, and never on the network of the campaign API.
"""

from typing import Any

from argos_ai.api.app import create_app
from argos_ai.backends.fake import FakeBackend
from argos_ai.gateway import Gateway
from fastapi.testclient import TestClient

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["category"],
    "properties": {"category": {"type": "string"}},
}
REQUEST = {
    "service": "inventory",
    "system": "Clasifica.",
    "user": "columna: national_id",
    "schema": SCHEMA,
}


def _client(replies: list[str], quotas: dict[str, int] | None = None) -> TestClient:
    gateway = Gateway(
        FakeBackend.of(replies),
        journal=lambda _: None,
        usage=lambda _: None,
        quotas=quotas if quotas is not None else {"inventory": 1_000_000},
    )
    return TestClient(create_app(gateway))


def test_the_health_check_answers() -> None:
    assert _client([]).get("/health").json() == {"status": "ok", "service": "argos-ai-gateway"}


def test_a_completion_comes_back_with_its_hash_and_never_its_prompt() -> None:
    response = _client(['{"category": "official_identifier"}']).post("/v1/chat_json", json=REQUEST)
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"category": "official_identifier"}
    assert len(body["prompt_sha256"]) == 64
    assert "national_id" not in response.text


def test_a_spent_quota_is_a_429() -> None:
    response = _client(['{"category": "x"}'], quotas={}).post("/v1/chat_json", json=REQUEST)
    assert response.status_code == 429


def test_an_answer_the_guardrails_refuse_is_a_422() -> None:
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    response = _client(['{"answer": "El sistema es conforme."}']).post(
        "/v1/chat_json", json={**REQUEST, "schema": schema}
    )
    assert response.status_code == 422
    assert "veredicto_no_citado" in response.text


def test_an_answer_that_never_fits_the_schema_is_a_502() -> None:
    response = _client(['{"otra": 1}', '{"otra": 2}']).post("/v1/chat_json", json=REQUEST)
    assert response.status_code == 502


def test_an_unknown_priority_is_refused_before_the_gateway() -> None:
    response = _client([]).post("/v1/chat_json", json={**REQUEST, "priority": "urgentisima"})
    assert response.status_code == 422
