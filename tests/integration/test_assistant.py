"""ARG-058 · the four tools against the real database, and one question end to end (F06-11)."""

import asyncio
import json

import pytest
from argos_ai.assistant.agent import ask
from argos_ai.assistant.tools import default_toolbox
from argos_ai.backends.fake import FakeBackend
from argos_ai.quotas import postgres_gateway
from argos_ai.rag.embeddings import HashEmbedder
from argos_ai.rag.indexer import index_document

from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore

from .inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

EMBEDDER = HashEmbedder()
RGPD = """Artículo 32. Seguridad del tratamiento
1. El responsable aplicará medidas técnicas apropiadas, entre otras:
a) la seudonimización y el cifrado de los datos personales;
"""


def test_the_graph_tool_uses_the_whitelisted_selector(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    classify_new_columns(GraphStore(migrated_db), probe_runner(migrated_db), system_id)
    tools = default_toolbox(migrated_db, EMBEDDER)
    result = tools["query_graph"].run({"selector": {"label": "Column", "category": "official"}})
    names = {node["qualified_name"] for node in result["nodes"]}
    assert "clinic.patients.national_id" in names


def test_the_graph_tool_refuses_a_field_outside_the_whitelist(migrated_db: str) -> None:
    tools = default_toolbox(migrated_db, EMBEDDER)
    with pytest.raises(ValueError, match="not allowed"):
        tools["query_graph"].run({"selector": {"cypher": "MATCH (n) DETACH DELETE n"}})


def test_the_finding_tool_counts_with_typed_filters(migrated_db: str) -> None:
    tools = default_toolbox(migrated_db, EMBEDDER)
    assert tools["finding_status"].run({"severity": "critical"}) == {
        "total": 0,
        "by_status_and_severity": [],
    }


def test_the_regulation_tool_returns_citable_fragments(migrated_db: str) -> None:
    index_document(migrated_db, "RGPD", "norm", RGPD, "RGPD", EMBEDDER)
    tools = default_toolbox(migrated_db, EMBEDDER)
    result = tools["search_regulation"].run({"question": "32.1.a cifrado"})
    assert "RGPD art. 32.1.a" in [fragment["reference"] for fragment in result["fragments"]]


def test_the_coverage_tool_reads_the_catalogue(migrated_db: str) -> None:
    scan_and_ingest(migrated_db, "dev-source-postgres")
    tools = default_toolbox(migrated_db, EMBEDDER)
    assert isinstance(tools["inventory_coverage"].run({})["systems"], list)


def test_a_question_end_to_end_with_the_real_tools(migrated_db: str) -> None:
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
    backend = FakeBackend.of([json.dumps(reply) for reply in replies])
    gateway = postgres_gateway(migrated_db, backend)
    result = asyncio.run(
        ask(
            "¿qué pide el RGPD de cifrado y cuántos críticos hay?",
            gateway,
            default_toolbox(migrated_db, EMBEDDER),
        )
    )
    assert result.complete and result.calls == ["search_regulation", "finding_status"]
    assert "RGPD art. 32.1.a" in backend.last_user, "the tool result reached the model"
