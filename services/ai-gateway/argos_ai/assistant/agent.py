"""The console assistant: an agent with four closed tools (ARG-058).

It answers questions from three worlds — the regulation, the state of the client, and both at once
— by choosing among four read-only tools with typed parameters (`tools`), iterating until it can
answer. Three things are fixed and none of them can be moved from the question:

- **the budget**: at most `MAX_TOOL_CALLS` tool calls per question; if that is not enough, the
  answer says so instead of guessing;
- **the arguments**: validated against the tool's schema before the tool runs; an invalid call is
  answered with the error, so the model can correct itself, and it still spends budget;
- **the sources**: every source the answer quotes has to be a tool it actually called, the same way
  a citation of the RAG has to be a fragment it retrieved.

The conversation lives only in memory, for the question at hand. What is logged is the hash of each
prompt, by the gateway, never its content.
"""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from argos_ai.assistant.tools import Tool
from argos_ai.gateway import Gateway
from argos_common.errors import ArgosError

MAX_TOOL_CALLS = 5
SERVICE = "assistant"
SYSTEM_PROMPT = (
    "Eres el asistente de la consola de ARGOS. Respondes preguntas sobre la normativa y sobre el "
    "estado del cliente usando solo estas herramientas de lectura: {tools}. En cada paso "
    'devuelves JSON: o bien {{"action": "tool", "tool": nombre, "arguments": {{...}}}}, o bien '
    '{{"action": "answer", "answer": texto, "sources": [{{"tool": nombre, "detail": texto}}]}}. '
    "Cita el origen de cada dato: el artículo para la norma, el recuento con su herramienta para "
    "el estado. Tienes como mucho {budget} consultas. No decides si algo cumple: eso no es tuyo."
)
STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"enum": ["tool", "answer"]},
        "tool": {"type": "string"},
        "arguments": {"type": "object"},
        "answer": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool", "detail"],
                "properties": {"tool": {"type": "string"}, "detail": {"type": "string"}},
            },
        },
    },
}
OUT_OF_BUDGET = (
    "No he podido responder con las {budget} consultas que tengo por pregunta. "
    "Reformúlala más acotada o divídela en dos."
)


class AssistantError(ArgosError):
    """The answer quotes a source it did not consult."""


@dataclass(frozen=True, slots=True)
class Answer:
    answer: str
    sources: list[dict[str, str]]
    complete: bool
    calls: list[str] = field(default_factory=list)


def _step_result(tools: Mapping[str, Tool], step: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """(tool name, what it returned or why it did not run). Never an exception."""
    name = str(step.get("tool", ""))
    tool = tools.get(name)
    if tool is None:
        return name, {"error": f"no existe la herramienta {name!r}; solo {sorted(tools)}"}
    arguments = dict(step.get("arguments") or {})
    try:
        jsonschema.Draft202012Validator(tool.schema).validate(arguments)
    except jsonschema.ValidationError as exc:
        return name, {"error": f"argumentos no válidos para {name}: {exc.message}"}
    return name, {"result": tool.run(arguments)}


async def ask(question: str, gateway: Gateway, tools: Mapping[str, Tool]) -> Answer:
    """Answer one console question, within the budget and with checked sources."""
    system = SYSTEM_PROMPT.format(tools=", ".join(sorted(tools)), budget=MAX_TOOL_CALLS)
    transcript: list[str] = [f"Pregunta: {question}"]
    used: list[str] = []  # every call, failed ones included: they spend budget too
    consulted: set[str] = set()  # only the calls that returned data can be quoted as sources
    for _ in range(MAX_TOOL_CALLS + 1):
        answer = await gateway.chat_json(
            SERVICE, system, "\n".join(transcript), STEP_SCHEMA, priority="interactive"
        )
        step = answer.data
        if step.get("action") == "answer":
            sources = [dict(source) for source in step.get("sources", [])]
            unused = sorted({source["tool"] for source in sources} - consulted)
            if unused:
                raise AssistantError(f"la respuesta cita herramientas que no consultó: {unused}")
            return Answer(str(step.get("answer", "")), sources, True, used)
        if len(used) >= MAX_TOOL_CALLS:
            break
        name, outcome = await asyncio.to_thread(_step_result, tools, step)
        used.append(name)
        if "result" in outcome:
            consulted.add(name)
        transcript.append(
            f"Consulta {len(used)} a {name}: {json.dumps(outcome, ensure_ascii=False, default=str)}"
        )
    return Answer(OUT_OF_BUDGET.format(budget=MAX_TOOL_CALLS), [], False, used)
