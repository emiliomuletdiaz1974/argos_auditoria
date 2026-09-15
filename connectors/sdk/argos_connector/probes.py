"""Normalised probe types shared by every connector (ARG-011)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PROBE_KINDS = frozenset({"scan_schema", "count", "sample", "check_config"})


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    kind: str
    target: str
    statement: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    probe_id: str
    kind: str
    ok: bool
    data: dict[str, Any]  # always minimised: counts, digests, schemas
    duration_ms: int
    rows_touched: int
    journal_seq: int  # journal entry written BEFORE the probe was sent
