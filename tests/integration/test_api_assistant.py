"""ARG-078 · the assistant over the v1: the API asks the AI gateway, and only by HTTP.

The agent and its four closed tools run inside the gateway —its network, its database role with no
privilege over a verdict—; the API forwards the question and returns what came back: the answer,
its citations, the tools consulted and, when there is not enough to go on, the honest refusal. It is
always marked as assisted text: it is not a verdict. Without the local model the route says so.
"""

import json
from typing import Any, cast

import httpx
import pytest
from argos_ai.api.app import create_app as create_gateway
from argos_ai.assistant.agent import MAX_TOOL_CALLS
from argos_ai.assistant.tools import default_toolbox
from argos_ai.backends.fake import FakeBackend
from argos_ai.backends.openai_compatible import OpenAiCompatibleBackend
from argos_ai.quotas import postgres_gateway
from argos_ai.rag.embeddings import HashEmbedder
from argos_ai.rag.indexer import index_document
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.assistant import AssistantClient
from argos_auth import Identity, JwtValidator

pytestmark = pytest.mark.integration

EMBEDDER = HashEmbedder()
QUESTION = {"question": "¿qué pide el RGPD de cifrado y cuántos críticos hay?"}
RGPD = """Artículo 32. Seguridad del tratamiento
1. El responsable aplicará medidas técnicas apropiadas, entre otras:
a) la seudonimización y el cifrado de los datos personales;
"""
NOWHERE = "http://127.0.0.1:9"


class PersonValidator:
    def validate(self, token: str) -> Identity:
        return Identity(sub=token, name=token, roles=frozenset({token}))


def _as(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}


def _api(dsn: str, assistant: AssistantClient | None) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=dsn, assistant=assistant))


def _through_gateway(dsn: str, replies: list[dict[str, Any]]) -> AssistantClient:
    """The real gateway application, with a model that answers what the test says."""
    backend = FakeBackend.of([json.dumps(reply) for reply in replies])
    gateway = create_gateway(postgres_gateway(dsn, backend), tools=default_toolbox(dsn, EMBEDDER))
    return AssistantClient("http://ai-gateway", transport=httpx.ASGITransport(app=gateway))


def test_an_answer_comes_with_its_citations_and_the_tools_it_consulted(migrated_db: str) -> None:
    index_document(migrated_db, "RGPD", "norm", RGPD, "RGPD", EMBEDDER)
    replies = [
        {"action": "tool", "tool": "search_regulation", "arguments": {"question": "cifrado 32"}},
        {"action": "tool", "tool": "finding_status", "arguments": {"severity": "critical"}},
        {
            "action": "answer",
            "answer": "El art. 32.1.a pide cifrado; no hay hallazgos críticos abiertos.",
            "sources": [
                {"tool": "search_regulation", "detail": "RGPD art. 32.1.a"},
                {"tool": "finding_status", "detail": "0 críticos"},
            ],
        },
    ]
    answer = _api(migrated_db, _through_gateway(migrated_db, replies)).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("dpo_reviewer")
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["calls"] == ["search_regulation", "finding_status"]
    assert [s["detail"] for s in body["sources"]] == ["RGPD art. 32.1.a", "0 críticos"]
    assert body["complete"] is True
    assert body["assisted"] is True
    assert "no es un veredicto" in body["notice"]


def test_when_there_is_not_enough_it_says_so(migrated_db: str) -> None:
    looping = [{"action": "tool", "tool": "inventory_coverage", "arguments": {}}] * (
        MAX_TOOL_CALLS + 1
    )
    answer = _api(migrated_db, _through_gateway(migrated_db, looping)).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("campaign_manager")
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["complete"] is False
    assert body["sources"] == []
    assert str(MAX_TOOL_CALLS) in body["answer"]
    assert body["assisted"] is True


def test_without_the_local_model_the_route_says_the_model_is_not_there(migrated_db: str) -> None:
    gateway = create_gateway(
        postgres_gateway(migrated_db, OpenAiCompatibleBackend(f"{NOWHERE}/v1", "argos-llm")),
        tools=default_toolbox(migrated_db, EMBEDDER),
    )
    client = AssistantClient("http://ai-gateway", transport=httpx.ASGITransport(app=gateway))
    answer = _api(migrated_db, client).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("dpo_reviewer")
    )
    assert answer.status_code == 503
    assert answer.headers["content-type"].startswith("application/problem+json")
    assert "model" in answer.json()["detail"]


def test_without_the_gateway_the_route_says_so_too(migrated_db: str) -> None:
    answer = _api(migrated_db, AssistantClient(NOWHERE)).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("dpo_reviewer")
    )
    assert answer.status_code == 503
    assert "gateway" in answer.json()["detail"]


def test_an_api_without_an_assistant_does_not_pretend_to_have_one(migrated_db: str) -> None:
    answer = _api(migrated_db, None).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("dpo_reviewer")
    )
    assert answer.status_code == 503


def test_an_auditor_does_not_spend_the_quota_of_the_local_model(migrated_db: str) -> None:
    answer = _api(migrated_db, AssistantClient(NOWHERE)).post(
        f"{API_PREFIX}/assistant/ask", json=QUESTION, headers=_as("read_only_auditor")
    )
    assert answer.status_code == 403
