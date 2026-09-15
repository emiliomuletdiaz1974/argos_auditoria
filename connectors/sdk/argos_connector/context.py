"""What a connector receives instead of reaching for globals (ARG-011)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .minimize import ValueHasher
from .probes import ProbeSpec


class ProbeJournal(Protocol):
    def register(self, spec: ProbeSpec) -> int: ...

    def complete(
        self,
        journal_seq: int,
        *,
        ok: bool,
        duration_ms: int,
        rows: int,
        error: str | None = None,
    ) -> None: ...

    def reject(self, spec: ProbeSpec, reason: str) -> int: ...


class ProbeBudget(Protocol):
    @property
    def max_rows_per_probe(self) -> int: ...

    def acquire(self) -> None: ...

    def observe_latency(self, ms: int) -> None: ...


@dataclass(frozen=True)
class ConnectorContext:
    journal: ProbeJournal
    budget: ProbeBudget
    hasher: ValueHasher
    credentials: Mapping[str, str]
