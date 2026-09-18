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
from datetime import UTC, date, datetime
from typing import Any

import jsonschema

from argos_ai.backends.base import Backend
from argos_ai.guardrails import check_output, scrub_input
from argos_common.errors import ArgosError

PRIORITIES = ("interactive", "batch")
DEFAULT_SLOTS: Mapping[str, int] = {"interactive": 12, "batch": 8}
# Tokens held against the quota while a request is in flight: a prompt plus two capped answers.
DEFAULT_RESERVATION = 8_192
REPAIR_INSTRUCTION = (
    "Tu respuesta anterior no encaja en el esquema. Corrígela y devuelve solo JSON válido.\n"
    "Respuesta anterior: {answer}\nError: {error}"
)


class GatewayError(ArgosError):
    """The gateway cannot serve this request."""


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
        reservation: int = DEFAULT_RESERVATION,
        today: Callable[[], date] | None = None,
        reload_quotas: Callable[[], Mapping[str, int]] | None = None,
        verdict_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self._backend = backend
        self._journal = journal
        self._usage = usage
        self._quotas = dict(quotas)
        self._spent: dict[str, int] = dict(spent or {})
        self._reserved: dict[str, int] = {}
        sizes = {**DEFAULT_SLOTS, **dict(slots or {})}
        self._slots = {name: asyncio.Semaphore(sizes[name]) for name in PRIORITIES}
        self._model = model
        self._reservation = reservation
        self._today = today or (lambda: datetime.now(UTC).date())
        self._reload_quotas = reload_quotas
        self._verdict_exists = verdict_exists
        self._day = self._today()

    def spent(self, service: str) -> int:
        return self._spent.get(service, 0)

    def _roll_day(self) -> None:
        """A daily quota is per day: the counter starts again, and the table is read again."""
        today = self._today()
        if today == self._day:
            return
        self._day = today
        self._spent.clear()
        if self._reload_quotas is not None:
            self._quotas = dict(self._reload_quotas())

    def _reserve(self, service: str) -> None:
        """Take the reservation before calling, so parallel requests see each other's cost."""
        self._roll_day()
        budget = self._quotas.get(service)
        if budget is None:
            raise QuotaExceededError(f"the service {service!r} has no declared quota")
        committed = self._spent.get(service, 0) + self._reserved.get(service, 0)
        if committed + self._reservation > budget:
            raise QuotaExceededError(f"the service {service!r} spent its daily quota")
        self._reserved[service] = self._reserved.get(service, 0) + self._reservation

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
        clean_system, substituted_system = scrub_input(system)
        clean_user, substituted_user = scrub_input(user)
        substitutions = substituted_system + substituted_user
        digest = prompt_hash(clean_system, clean_user)

        self._reserve(service)
        # What the model consumed is spent whatever happens next: a failed or rejected answer
        # costs the same inference as a good one.
        cost = [0, 0]
        try:
            async with self._slots[priority]:
                data, repaired = await self._complete(clean_system, clean_user, schema, cost)
            check_output(data, self._verdict_exists)
        finally:
            self._reserved[service] -= self._reservation
            self._spent[service] = self._spent.get(service, 0) + cost[0] + cost[1]
            if cost[0] or cost[1]:
                self._usage(
                    {
                        "service": service,
                        "model": self._model,
                        "prompt_sha256": digest,
                        "tokens_in": cost[0],
                        "tokens_out": cost[1],
                    }
                )
        tokens_in, tokens_out = cost
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
        self, system: str, user: str, schema: dict[str, Any], cost: list[int]
    ) -> tuple[dict[str, Any], bool]:
        """The parsed answer and whether it needed the repair; `cost` adds up every call."""
        completion = await self._call(system, user, schema)
        cost[0] += completion.tokens_in
        cost[1] += completion.tokens_out
        parsed, error = _parse(completion.text, schema)
        if error is None:
            return parsed, False
        repair = REPAIR_INSTRUCTION.format(answer=completion.text, error=error)
        second = await self._call(system, f"{user}\n\n{repair}", schema)
        cost[0] += second.tokens_in
        cost[1] += second.tokens_out
        parsed, error = _parse(second.text, schema)
        if error is not None:
            raise GatewayError(f"the answer does not fit the schema after one repair: {error}")
        return parsed, True

    async def _call(self, system: str, user: str, schema: dict[str, Any]) -> Any:
        try:
            return await self._backend.complete(system, user, schema)
        except KeyError as exc:  # the deterministic backend does not know this input
            raise GatewayError(f"no recorded answer: {exc}") from exc


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
