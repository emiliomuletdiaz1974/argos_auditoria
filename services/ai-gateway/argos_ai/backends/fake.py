"""The deterministic backend: the same prompt always gives the same answer (ADR-0009).

This is product, not test scaffolding. Without it the CI would depend on a GPU and on the mood of
a model, and a golden set that changes under your feet measures nothing. It answers from a file
keyed by the hash of the prompt, and **an input it does not know is an error**: a silent default
would turn a missing case into a green suite.
"""

import json
from pathlib import Path

from .base import Completion


class FakeBackend:
    """Answers recorded by prompt hash, or a fixed queue of answers for a test."""

    def __init__(self, responses: Path | None = None, delay: float = 0.0) -> None:
        self._recorded: dict[str, str] = {}
        if responses is not None:
            self._recorded = dict(json.loads(responses.read_text(encoding="utf-8")))
        self._queue: list[str] = []
        self._delay = delay
        self.calls = 0
        self.last_system = ""
        self.last_user = ""

    @classmethod
    def of(cls, answers: list[str], delay: float = 0.0) -> "FakeBackend":
        """A queue of answers, in order: the shape a test needs to drive a repair cycle."""
        backend = cls(delay=delay)
        backend._queue = list(answers)
        return backend

    async def complete(
        self, system: str, user: str, schema: dict[str, object] | None = None
    ) -> Completion:
        import asyncio
        import hashlib

        if self._delay:
            await asyncio.sleep(self._delay)
        self.calls += 1
        self.last_system, self.last_user = system, user
        if self._queue:
            text = self._queue.pop(0)
        else:
            key = hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()
            if key not in self._recorded:
                raise KeyError(f"no recorded answer for {key[:12]}")
            text = self._recorded[key]
        return Completion(text=text, tokens_in=len(system) + len(user), tokens_out=len(text))
