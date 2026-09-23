"""ARG-055/058 · the assistant and the classifier within bounds (security review F09-02).

- SEC-043: one person cannot spend the assistant's daily quota for everybody.
- SEC-050: a tool that fails answers the model with its error; the question does not break, and
  the schema does not offer a selector field the tool cannot serve.
- SEC-052: the classifier records only proposals for columns of its batch, once, with a category
  the product knows; anything else would feed the next calibration with noise.
"""

import asyncio
import json
from typing import Any

import pytest
from argos_ai.assistant.agent import ask
from argos_ai.assistant.tools import TOOL_SCHEMAS, Tool
from argos_ai.backends.fake import FakeBackend
from argos_ai.classify.calibration import Calibrator
from argos_ai.classify.service import SemanticClassifier
from argos_ai.gateway import Gateway, QuotaExceededError

from argos_inventory.classify.assisted import ColumnContext

SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


# ---------- SEC-043 · a quota per person ----------


def _gateway(replies: int, quota: int, share: float) -> Gateway:
    backend = FakeBackend.of([json.dumps({"answer": "ok"})] * replies)
    return Gateway(
        backend,
        journal=lambda _: None,
        usage=lambda _: None,
        quotas={"assistant": quota},
        reservation=100,
        person_share=share,
    )


def test_one_person_spending_their_share_does_not_spend_anybody_elses() -> None:
    gateway = _gateway(replies=3, quota=1_000, share=0.1)  # 100 per person and day

    async def run() -> None:
        await gateway.chat_json("assistant", "s", "u", SCHEMA, person="user:ana")
        with pytest.raises(QuotaExceededError, match="user:ana"):
            await gateway.chat_json("assistant", "s", "u", SCHEMA, person="user:ana")
        await gateway.chat_json("assistant", "s", "u", SCHEMA, person="user:luis")

    asyncio.run(run())


def test_without_a_person_only_the_service_quota_applies() -> None:
    gateway = _gateway(replies=2, quota=1_000, share=0.1)

    async def run() -> None:
        await gateway.chat_json("assistant", "s", "u", SCHEMA)
        await gateway.chat_json("assistant", "s", "u", SCHEMA)

    asyncio.run(run())


# ---------- SEC-050 · a failing tool is an answer for the model ----------


def test_a_tool_error_goes_back_to_the_model_instead_of_breaking_the_question() -> None:
    def broken(_arguments: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("system_kind needs the system ids of that kind")

    tools = {name: Tool(name, TOOL_SCHEMAS[name], broken) for name in TOOL_SCHEMAS}
    replies = [
        {"action": "tool", "tool": "query_graph", "arguments": {"selector": {"label": "Column"}}},
        {"action": "refuse", "answer": "No he podido consultar el inventario."},
    ]
    backend = FakeBackend.of([json.dumps(reply) for reply in replies])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"assistant": 1_000_000}
    )
    result = asyncio.run(ask("¿cuántas columnas hay?", gateway, tools))
    assert result.refused is True
    assert "system_kind needs" in backend.last_user


def test_the_graph_tool_does_not_offer_a_field_it_cannot_serve() -> None:
    names = TOOL_SCHEMAS["query_graph"]["properties"]["selector"]["propertyNames"]["enum"]
    assert "system_kind" not in names


# ---------- SEC-052 · only what belongs to the batch is recorded ----------


def test_the_classifier_records_only_its_batch_once_and_known_categories() -> None:
    columns = [ColumnContext("k1", "email", "text", "crm.contacts", ("id",))]
    reply = {
        "items": [
            {"key": "k1", "category": "contact_data", "confidence": 0.9},
            {"key": "k1", "category": "personal_data", "confidence": 0.9},
            {"key": "k-other-table", "category": "contact_data", "confidence": 0.9},
            {"key": "k1", "category": "made_up", "confidence": 0.9},
        ]
    }
    recorded: list[dict[str, Any]] = []
    backend = FakeBackend.of([json.dumps(reply)])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"inventory": 1_000_000}
    )
    classifier = SemanticClassifier(gateway, Calibrator({}), record=recorded.extend)
    proposals = classifier.propose(columns)
    assert [(p.key, p.category) for p in proposals] == [("k1", "contact_data")]
    assert [(r["node_key"], r["category"]) for r in recorded] == [("k1", "contact_data")]
