"""The console assistant: an agent with four closed tools (ARG-058).

It answers questions from three worlds — the regulation, the state of the client, and both at once
— by choosing among four read-only tools with typed parameters (`tools`), iterating until it can
answer. Three things are fixed and none of them can be moved from the question:

- **the budget**: at most `MAX_TOOL_CALLS` tool calls per question; if that is not enough, the
  answer says so instead of guessing;
- **the arguments**: validated against the tool's schema before the tool runs; an invalid call is
  answered with the error, so the model can correct itself, and it still spends budget;
- **the sources**: every source the answer quotes has to be a tool it actually called, the same way
  a citation of the RAG has to be a fragment it retrieved; a normative source has to be one of the
  fragments the search returned, word for word;
- **the figures and the verdicts**: every number of the answer has to be one the tools returned (or
  the question asked), and it can only quote a verdict a tool returned in this conversation
  (security review F09-02, SEC-033 and SEC-034).

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
from argos_ai.reports.figures import extract_figures, unsupported_figures
from argos_common.errors import ArgosError

MAX_TOOL_CALLS = 5
SERVICE = "assistant"
SYSTEM_PROMPT = (
    "Eres el asistente de la consola de ARGOS. Respondes preguntas sobre la normativa y sobre el "
    "estado del cliente usando solo estas herramientas de lectura: {tools}. En cada paso "
    'devuelves JSON: o bien {{"action": "tool", "tool": nombre, "arguments": {{...}}}}, o bien '
    '{{"action": "answer", "answer": texto, "sources": [{{"tool": nombre, "detail": texto}}]}}, '
    'o bien {{"action": "refuse", "answer": texto}} si lo consultado no basta para responder. '
    "Cita el origen de cada dato con [n], el número de su fuente en sources: el artículo para la "
    "norma, el recuento con su herramienta para el estado. Tienes como mucho {budget} consultas. "
    "No decides si algo cumple: eso no es tuyo."
)
STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"enum": ["tool", "answer", "refuse"]},
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


REGULATION_TOOL = "search_regulation"


class AssistantError(ArgosError):
    """The answer quotes a source it did not consult."""


@dataclass(frozen=True, slots=True)
class Answer:
    answer: str
    sources: list[dict[str, str]]
    complete: bool
    calls: list[str] = field(default_factory=list)
    # The normative fragments the tools retrieved, so each citation unfolds to its text and, when
    # the assistant refuses, the person can judge the closest ones themselves.
    fragments: list[dict[str, str]] = field(default_factory=list)
    refused: bool = False


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


def _returned(value: Any, numbers: list[float], verdicts: set[str], key: str = "") -> None:
    """Every number and verdict id a tool returned, however deep it sits."""
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        numbers.append(float(value))
    elif isinstance(value, str):
        if "verdict" in key:
            verdicts.add(value)
        numbers.extend(figure for _, figure, _ in extract_figures(value))
    elif isinstance(value, Mapping):
        for name, item in value.items():
            _returned(item, numbers, verdicts, str(name))
    elif isinstance(value, list):
        for item in value:
            _returned(item, numbers, verdicts, key)


def _checked(
    step: Mapping[str, Any],
    consulted: set[str],
    fragments: list[dict[str, str]],
    numbers: list[float],
) -> list[dict[str, str]]:
    """The sources of an answer, or `AssistantError` naming what it could not back."""
    sources = [dict(source) for source in step.get("sources", [])]
    unused = sorted({source["tool"] for source in sources} - consulted)
    if unused:
        raise AssistantError(f"la respuesta cita herramientas que no consultó: {unused}")
    retrieved = {fragment["reference"] for fragment in fragments}
    invented = [
        source["detail"]
        for source in sources
        if source["tool"] == REGULATION_TOOL and source["detail"] not in retrieved
    ]
    if invented:
        raise AssistantError(f"la respuesta cita fragmentos que no se recuperaron: {invented}")
    stated = " ".join(
        [str(step.get("answer", ""))]
        + [source["detail"] for source in sources if source["tool"] != REGULATION_TOOL]
    )
    offending = unsupported_figures(stated, numbers)
    if offending:
        raise AssistantError(
            f"la respuesta da cifras que ninguna herramienta devolvió: {offending}"
        )
    return sources


def _fragments(result: Mapping[str, Any], seen: list[dict[str, str]]) -> list[dict[str, str]]:
    """The new fragments a regulation search returned, once each, in the order they came."""
    known = {fragment["reference"] for fragment in seen}
    new: list[dict[str, str]] = []
    for fragment in result.get("fragments", []):
        reference = str(fragment.get("reference", ""))
        if reference and reference not in known:
            known.add(reference)
            new.append({"reference": reference, "text": str(fragment.get("text", ""))})
    return new


async def ask(question: str, gateway: Gateway, tools: Mapping[str, Tool]) -> Answer:
    """Answer one console question, within the budget and with checked sources."""
    system = SYSTEM_PROMPT.format(tools=", ".join(sorted(tools)), budget=MAX_TOOL_CALLS)
    transcript: list[str] = [f"Pregunta: {question}"]
    used: list[str] = []  # every call, failed ones included: they spend budget too
    consulted: set[str] = set()  # only the calls that returned data can be quoted as sources
    fragments: list[dict[str, str]] = []
    # What the answer may state: the numbers of the question and of what the tools returned, and
    # the verdicts the tools returned. Nothing the model writes on its own.
    numbers: list[float] = [figure for _, figure, _ in extract_figures(question)]
    verdicts: set[str] = set()
    for _ in range(MAX_TOOL_CALLS + 1):
        answer = await gateway.chat_json(
            SERVICE,
            system,
            "\n".join(transcript),
            STEP_SCHEMA,
            priority="interactive",
            allowed_verdicts=frozenset(verdicts),
        )
        step = answer.data
        if step.get("action") == "answer":
            sources = _checked(step, consulted, fragments, numbers)
            return Answer(str(step.get("answer", "")), sources, True, used, fragments)
        if step.get("action") == "refuse":
            return Answer(str(step.get("answer", "")), [], False, used, fragments, refused=True)
        if len(used) >= MAX_TOOL_CALLS:
            break
        name, outcome = await asyncio.to_thread(_step_result, tools, step)
        used.append(name)
        if "result" in outcome:
            consulted.add(name)
            _returned(outcome["result"], numbers, verdicts)
            if name == REGULATION_TOOL:
                fragments.extend(_fragments(outcome["result"], fragments))
        transcript.append(
            f"Consulta {len(used)} a {name}: {json.dumps(outcome, ensure_ascii=False, default=str)}"
        )
    return Answer(OUT_OF_BUDGET.format(budget=MAX_TOOL_CALLS), [], False, used, fragments)
