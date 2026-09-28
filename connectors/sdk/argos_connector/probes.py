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


def sample_size(params: Mapping[str, Any], default: int, max_rows: int) -> int:
    """The `k` of a sample: a positive integer, never above the budget (quality review QA-027).

    A negative `k` meant no limit in SQLite (`LIMIT -1`), all but the last item in REST and an
    invalid `_count` in FHIR: anything that is not a positive integer is refused.
    """
    k = params.get("k", default)
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"the size of a sample must be a positive integer, not {k!r}")
    return min(k, max_rows)
