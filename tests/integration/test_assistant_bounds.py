"""ARG-058/078 · the assistant's tools within bounds, against the database (security review F09-02).

- SEC-047: every tool connection carries a statement timeout.
- SEC-048: a document of the client is never cited as regulation.
- SEC-043: the API tells the gateway who asks, so the quota is per person.
- The container of the gateway starts with its tools: without a model it says so, not that it has
  no tools.
"""

import json
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
import pytest
from argos_ai.assistant.tools import TOOL_STATEMENT_TIMEOUT, default_toolbox, timeboxed
from argos_ai.rag.chunking import Chunk
from argos_ai.rag.embeddings import HashEmbedder
from argos_ai.rag.indexer import index_chunks
from fastapi.testclient import TestClient

from argos_api.app import create_app
from argos_api.assistant import AssistantClient
from argos_auth import Identity, JwtValidator
from argos_tls import mtls_client

pytestmark = pytest.mark.integration

EMBEDDER = HashEmbedder()


def test_every_tool_connection_carries_a_statement_timeout(migrated_db: str) -> None:
    with psycopg.connect(timeboxed(migrated_db)) as conn:
        row = conn.execute("SHOW statement_timeout").fetchone()
    assert row is not None and row[0] == TOOL_STATEMENT_TIMEOUT


def test_a_client_document_is_never_cited_as_regulation(migrated_db: str) -> None:
    text = "cifrado de las copias de seguridad en el centro de datos del hospital"
    index_chunks(
        migrated_db,
        "politica-interna.md",
        "client",
        [Chunk("Política interna 4.2", "Copias", text)],
        EMBEDDER,
    )
    index_chunks(
        migrated_db,
        "rgpd.md",
        "norm",
        [Chunk("RGPD art. 32.1.a", "Seguridad", "la seudonimización y el cifrado de los datos")],
        EMBEDDER,
    )
    tools = default_toolbox(migrated_db, EMBEDDER)
    result = tools["search_regulation"].run({"question": "cifrado de las copias de seguridad"})
    references = [fragment["reference"] for fragment in result["fragments"]]
    assert "Política interna 4.2" not in references
    assert "RGPD art. 32.1.a" in references


class PersonValidator:
    def validate(self, token: str) -> Identity:
        return Identity(sub=token, name=token, roles=frozenset({"dpo_reviewer"}))


def test_the_api_tells_the_gateway_who_asks(migrated_db: str) -> None:
    sent: list[dict[str, Any]] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(503, json={"detail": "the local model is not available"})

    client = AssistantClient("http://ai-gateway", transport=httpx.MockTransport(gateway))
    api = TestClient(
        create_app(cast(JwtValidator, PersonValidator()), dsn=migrated_db, assistant=client)
    )
    api.post(
        "/api/v1/assistant/ask",
        json={"question": "¿qué pide el RGPD?"},
        headers={"Authorization": "Bearer ana"},
    )
    assert sent and sent[0]["person"] == "user:ana"


def test_the_gateway_container_starts_with_its_tools() -> None:
    # Over mutual TLS (F09-06): the host presents its own certificate of the internal CA.
    host_tls = Path(__file__).resolve().parents[2] / "deploy" / "dev" / "secrets" / "tls-host"
    with mtls_client(host_tls, timeout=30) as client:
        answer = client.post(
            "https://localhost:8005/v1/assistant/ask",
            json={"question": "¿qué pide el RGPD?", "person": "user:ana"},
        )
    assert answer.status_code == 503, answer.text
    assert "no assistant tools" not in answer.text
