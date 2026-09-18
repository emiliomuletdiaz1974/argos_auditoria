"""ARG-052 · the gateway is the only door to inference (F06-04).

Pure: the backend is the deterministic one, the journal and the usage log are collected in memory.
What is checked here is the contract the four trades depend on — forced JSON with one repair, a
quota that is looked at before calling and not after, a log that keeps the hash and never the
prompt, and an interactive queue that batch work cannot starve.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.gateway import Gateway, GatewayError, QuotaExceededError
from argos_ai.guardrails import OutputRejectedError

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["category"],
    "additionalProperties": False,
    "properties": {"category": {"type": "string"}},
}
SYSTEM = "Clasifica la columna."
USER = "columna: clinic.patients.national_id"


def _gateway(backend: FakeBackend, **kwargs: Any) -> Gateway:
    entries: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []
    gateway = Gateway(
        backend,
        journal=entries.append,
        usage=usage.append,
        quotas=kwargs.pop("quotas", {"classify": 1_000_000}),
        **kwargs,
    )
    gateway.entries = entries  # type: ignore[attr-defined]
    gateway.usage_rows = usage  # type: ignore[attr-defined]
    return gateway


def _ask(gateway: Gateway, **kwargs: Any) -> Any:
    return asyncio.run(
        gateway.chat_json(
            kwargs.pop("service", "classify"),
            kwargs.pop("system", SYSTEM),
            kwargs.pop("user", USER),
            kwargs.pop("schema", SCHEMA),
            **kwargs,
        )
    )


def test_an_answer_that_fits_the_schema_comes_back_parsed() -> None:
    gateway = _gateway(FakeBackend.of(['{"category": "official_identifier"}']))
    answer = _ask(gateway)
    assert answer.data == {"category": "official_identifier"}
    assert answer.repaired is False


def test_an_answer_that_does_not_fit_is_repaired_once() -> None:
    """The error goes back as feedback: one cycle, and the second answer has to hold."""
    backend = FakeBackend.of(['{"categoria": "dni"}', '{"category": "official_identifier"}'])
    gateway = _gateway(backend)
    answer = _ask(gateway)
    assert answer.data == {"category": "official_identifier"}
    assert answer.repaired is True
    assert backend.calls == 2
    assert "categoria" in backend.last_user, "the repair must carry the failed answer back"


def test_an_answer_that_still_does_not_fit_after_the_repair_is_an_error() -> None:
    backend = FakeBackend.of(['{"categoria": "dni"}', '{"tampoco": true}'])
    with pytest.raises(GatewayError, match="schema"):
        _ask(_gateway(backend))
    assert backend.calls == 2, "there is one repair, not an endless retry"


def test_an_answer_that_is_not_even_json_is_repaired_too() -> None:
    backend = FakeBackend.of(["lo siento, no puedo", '{"category": "personal_data"}'])
    assert _ask(_gateway(backend)).data == {"category": "personal_data"}


def test_the_quota_is_checked_before_calling_the_model() -> None:
    """Spending first and complaining later would make the quota decorative."""
    backend = FakeBackend.of(['{"category": "personal_data"}'])
    gateway = _gateway(backend, quotas={"classify": 10}, spent={"classify": 10})
    with pytest.raises(QuotaExceededError, match="classify"):
        _ask(gateway)
    assert backend.calls == 0


def test_a_service_without_a_declared_quota_cannot_spend() -> None:
    gateway = _gateway(FakeBackend.of(['{"category": "personal_data"}']), quotas={})
    with pytest.raises(QuotaExceededError):
        _ask(gateway, service="assistant")


def test_the_log_keeps_the_hash_and_never_the_prompt() -> None:
    gateway = _gateway(FakeBackend.of(['{"category": "personal_data"}']))
    answer = _ask(gateway)
    [row] = gateway.usage_rows  # type: ignore[attr-defined]
    assert row["prompt_sha256"] == answer.prompt_sha256
    assert row["service"] == "classify" and row["tokens_in"] > 0
    written = json.dumps([row, *gateway.entries], ensure_ascii=False)  # type: ignore[attr-defined]
    assert USER not in written and SYSTEM not in written


def test_the_hash_is_the_one_of_the_prompt_that_was_sent() -> None:
    gateway = _gateway(FakeBackend.of(['{"category": "personal_data"}']))
    answer = _ask(gateway)
    expected = hashlib.sha256(f"{SYSTEM}\n{USER}".encode()).hexdigest()
    assert answer.prompt_sha256 == expected


def test_the_input_is_scrubbed_before_it_reaches_the_model() -> None:
    backend = FakeBackend.of(['{"category": "official_identifier"}'])
    gateway = _gateway(backend)
    answer = _ask(gateway, user="el valor de ejemplo es 99992001F")
    assert "99992001F" not in backend.last_user
    assert "[DNI-1]" in backend.last_user
    assert answer.substitutions == 1


def test_an_answer_that_decides_conformity_is_rejected() -> None:
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    backend = FakeBackend.of(['{"answer": "El sistema clinic es conforme."}'])
    with pytest.raises(OutputRejectedError):
        _ask(_gateway(backend), schema=schema)


def test_the_interactive_queue_is_not_starved_by_batch_work() -> None:
    """An assistant question must not wait behind the nightly classification."""
    backend = FakeBackend.of(['{"category": "personal_data"}'] * 40, delay=0.02)
    gateway = _gateway(
        backend,
        quotas={"classify": 1_000_000, "assistant": 1_000_000},
        slots={"batch": 1, "interactive": 2},
    )

    async def run() -> float:
        batch = [
            gateway.chat_json("classify", SYSTEM, f"{USER} {n}", SCHEMA, priority="batch")
            for n in range(20)
        ]
        started = asyncio.get_running_loop().time()
        pending = [asyncio.create_task(task) for task in batch]
        await asyncio.sleep(0.01)
        await gateway.chat_json("assistant", SYSTEM, USER, SCHEMA, priority="interactive")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.gather(*pending)
        return elapsed

    assert asyncio.run(run()) < 0.2, "the interactive question waited behind the batch queue"


def test_an_unknown_priority_is_an_error() -> None:
    with pytest.raises(GatewayError, match="priority"):
        _ask(_gateway(FakeBackend.of(["{}"])), priority="urgentisima")


def test_the_deterministic_backend_answers_by_the_hash_of_its_input(tmp_path: Path) -> None:
    """This is why the CI is reproducible: the same prompt, the same answer, no model."""
    key = hashlib.sha256(f"{SYSTEM}\n{USER}".encode()).hexdigest()
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({key: '{"category": "personal_data"}'}), encoding="utf-8")
    gateway = _gateway(FakeBackend(path))
    assert _ask(gateway).data == {"category": "personal_data"}


def test_the_deterministic_backend_refuses_an_input_it_does_not_know(tmp_path: Path) -> None:
    """A missing case is an error, not a silent pass that makes the suite meaningless."""
    path = tmp_path / "responses.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(GatewayError, match="no recorded answer"):
        _ask(_gateway(FakeBackend(path)))
