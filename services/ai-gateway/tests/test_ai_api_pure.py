"""ARG-052 · the gateway as a service: the internal door other services knock on (F06-13).

Two endpoints, as the phase document designs them: `/health` and `/v1/chat_json`. It is internal:
reachable only on the network of the AI layer, and never on the network of the campaign API.
"""

from typing import Any

import httpx
from argos_ai.api.app import create_app
from argos_ai.backends.base import Completion
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


class UnreachableModel:
    """The local model server is not there (F06-05 not done yet, or it fell over)."""

    async def complete(
        self, system: str, user: str, schema: dict[str, object] | None = None
    ) -> Completion:
        raise httpx.ConnectError("connection refused")


def _gateway_without_model() -> Gateway:
    return Gateway(
        UnreachableModel(),
        journal=lambda _: None,
        usage=lambda _: None,
        quotas={"inventory": 1_000_000, "assistant": 1_000_000},
    )


def test_without_the_model_a_completion_is_a_503_that_says_why() -> None:
    client = TestClient(create_app(_gateway_without_model()))
    response = client.post("/v1/chat_json", json=REQUEST)
    assert response.status_code == 503
    assert "model" in response.json()["detail"]


def test_the_assistant_runs_inside_the_gateway_with_its_closed_tools() -> None:
    from argos_ai.assistant.tools import Tool

    counted = Tool("finding_status", {"type": "object"}, lambda arguments: {"open": 2})
    replies = [
        '{"action": "tool", "tool": "finding_status", "arguments": {}}',
        '{"action": "answer", "answer": "Hay 2 abiertos.",'
        ' "sources": [{"tool": "finding_status", "detail": "2 abiertos"}]}',
    ]
    gateway = Gateway(
        FakeBackend.of(replies),
        journal=lambda _: None,
        usage=lambda _: None,
        quotas={"assistant": 1_000_000},
    )
    client = TestClient(create_app(gateway, tools={"finding_status": counted}))
    response = client.post(
        "/v1/assistant/ask", json={"question": "¿cuántos abiertos?", "person": "user:ana"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hay 2 abiertos."
    assert body["calls"] == ["finding_status"]
    assert body["sources"] == [{"tool": "finding_status", "detail": "2 abiertos"}]
    assert body["complete"] is True
    assert body["assisted"] is True


def test_the_assistant_without_the_model_is_a_503() -> None:
    client = TestClient(create_app(_gateway_without_model(), tools={}))
    response = client.post(
        "/v1/assistant/ask", json={"question": "¿cuántos abiertos?", "person": "user:ana"}
    )
    assert response.status_code == 503


def test_a_gateway_without_tools_does_not_pretend_to_have_an_assistant() -> None:
    client = TestClient(create_app(_gateway_without_model()))
    response = client.post(
        "/v1/assistant/ask", json={"question": "¿cuántos abiertos?", "person": "user:ana"}
    )
    assert response.status_code == 503
    assert "assistant" in response.json()["detail"]


def test_the_assistant_needs_to_know_who_asks() -> None:
    """Without the person the quota would be everybody's again (SEC-043)."""
    client = TestClient(create_app(_gateway_without_model(), tools={}))
    response = client.post("/v1/assistant/ask", json={"question": "¿cuántos abiertos?"})
    assert response.status_code == 422
