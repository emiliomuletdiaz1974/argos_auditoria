"""The contract every backend honours."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Completion:
    """What a backend gives back: the text and what it cost."""

    text: str
    tokens_in: int
    tokens_out: int


class Backend(Protocol):
    """A server that speaks the OpenAI-compatible completion API.

    `schema` is passed through so a backend that supports guided decoding can force the shape.
    The gateway validates the answer anyway: forcing is an optimisation, never the guarantee.
    """

    async def complete(
        self, system: str, user: str, schema: dict[str, object] | None = None
    ) -> Completion: ...
