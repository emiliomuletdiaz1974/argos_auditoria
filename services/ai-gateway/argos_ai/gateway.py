"""The AI gateway: the only door to inference (ARG-052).

If every service spoke to the model directly there would be no quotas —the console assistant could
starve the nightly classification—, no homogeneous log, and no single place to apply the guardrails.
The gateway concentrates the four things:

- **a queue with two priorities**: interactive (assistant and console) reserves slots so batch work
  cannot starve it;
- **a daily token quota per service**, looked at *before* calling: spending first and complaining
  afterwards would make the quota decorative;
- **the log in the chained journal with the hash of the prompt, never the prompt**, because a prompt
  can carry client metadata;
- **forced JSON with one repair cycle**: the schema travels to the backend so it can guide the
  decoding, but the answer is validated here in any case, and a first answer that does not fit goes
  back with its error as feedback. One cycle, not an endless retry.

The guardrails of ARG-060 are applied here, on the way in and on the way out. This module has no
route to the evaluator, and `tests/architecture/ai_boundary.py` makes sure it never grows one.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jsonschema

from argos_ai.backends.base import Backend
from argos_ai.guardrails import check_output, scrub_input
from argos_common.errors import ArgosError

PRIORITIES = ("interactive", "batch")
DEFAULT_SLOTS: Mapping[str, int] = {"interactive": 12, "batch": 8}
REPAIR_INSTRUCTION = (
    "Tu respuesta anterior no encaja en el esquema. Corrígela y devuelve solo JSON válido.\n"
    "Respuesta anterior: {answer}\nError: {error}"
)


class GatewayError(ArgosError):
    """The gateway cannot serve this request."""


class ModelUnavailableError(GatewayError):
    """The local model server does not answer: not deployed yet, or down."""


class QuotaExceededError(GatewayError):
    """The service has spent its budget for the day."""


@dataclass(frozen=True, slots=True)
class Answer:
    data: dict[str, Any]
    prompt_sha256: str
    tokens_in: int
    tokens_out: int
    repaired: bool
    substitutions: int


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()


class Gateway:
    """Queues, quotas, forced JSON and a log that keeps hashes.

    The journal and the usage log are injected so the gateway can be exercised whole without a
    database; the process that runs it in the appliance passes the PostgreSQL ones.
    """

    def __init__(
        self,
        backend: Backend,
        journal: Callable[[dict[str, Any]], None],
        usage: Callable[[dict[str, Any]], None],
        quotas: Mapping[str, int],
        spent: Mapping[str, int] | None = None,
        slots: Mapping[str, int] | None = None,
        model: str = "argos-llm",
    ) -> None:
        self._backend = backend
        self._journal = journal
        self._usage = usage
        self._quotas = dict(quotas)
        self._spent: dict[str, int] = dict(spent or {})
        sizes = {**DEFAULT_SLOTS, **dict(slots or {})}
        self._slots = {name: asyncio.Semaphore(sizes[name]) for name in PRIORITIES}
        self._model = model

    def _check_quota(self, service: str) -> None:
        budget = self._quotas.get(service)
        if budget is None:
            raise QuotaExceededError(f"the service {service!r} has no declared quota")
        if self._spent.get(service, 0) >= budget:
            raise QuotaExceededError(f"the service {service!r} spent its daily quota")

    async def chat_json(
        self,
        service: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        priority: str = "batch",
    ) -> Answer:
        if priority not in PRIORITIES:
            raise GatewayError(f"unknown priority: {priority!r}")
        self._check_quota(service)
        clean_system, substituted_system = scrub_input(system)
        clean_user, substituted_user = scrub_input(user)
        substitutions = substituted_system + substituted_user
        digest = prompt_hash(clean_system, clean_user)

        async with self._slots[priority]:
            data, tokens_in, tokens_out, repaired = await self._complete(
                clean_system, clean_user, schema
            )
        check_output(data)
        self._spent[service] = self._spent.get(service, 0) + tokens_in + tokens_out
        row = {
            "service": service,
            "model": self._model,
            "prompt_sha256": digest,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
        self._usage(row)
        self._journal(
            {
                "action": "ai.completion",
                "service": service,
                "prompt_sha256": digest,
                "repaired": repaired,
                "substitutions": substitutions,
            }
        )
        return Answer(data, digest, tokens_in, tokens_out, repaired, substitutions)

    async def _complete(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], int, int, bool]:
        completion = await self._call(system, user, schema)
        tokens_in, tokens_out = completion.tokens_in, completion.tokens_out
        parsed, error = _parse(completion.text, schema)
        if error is None:
            return parsed, tokens_in, tokens_out, False
        repair = REPAIR_INSTRUCTION.format(answer=completion.text, error=error)
        second = await self._call(system, f"{user}\n\n{repair}", schema)
        tokens_in += second.tokens_in
        tokens_out += second.tokens_out
        parsed, error = _parse(second.text, schema)
        if error is not None:
            raise GatewayError(f"the answer does not fit the schema after one repair: {error}")
        return parsed, tokens_in, tokens_out, True

    async def _call(self, system: str, user: str, schema: dict[str, Any]) -> Any:
        try:
            return await self._backend.complete(system, user, schema)
        except KeyError as exc:  # the deterministic backend does not know this input
            raise GatewayError(f"no recorded answer: {exc}") from exc
        except httpx.HTTPError as exc:  # an unreachable model is a state to report, not a crash
            raise ModelUnavailableError(f"the local model is not available: {exc}") from exc


def _parse(text: str, schema: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """The answer as a document, or the reason it is not one. Never an exception."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"the answer is not JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "the answer is not a JSON object"
    try:
        jsonschema.Draft202012Validator(schema).validate(data)
    except jsonschema.ValidationError as exc:
        return data, str(exc.message)
    return data, None
