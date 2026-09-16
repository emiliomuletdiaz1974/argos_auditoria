"""Rescan policy: each system gets its fair cadence (ARG-030, deviation note ARG-029-030).

Pure and deterministic, so the planner workflow can use it inside the Temporal sandbox.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

CADENCE_HOURS = {"structure": 24}
NEVER_SCANNED_AGE = 999.0
LAUNCH_THRESHOLD = 1.0
MAX_PARALLEL = 4  # size M; an observed-load limit arrives with ARG-094
RECENT_DELTA_CAP = 5
RECENT_DELTA_WEIGHT = 0.2
AI_PENDING_BONUS = 0.5


@dataclass(frozen=True, slots=True)
class SystemState:
    system_id: str
    name: str
    kind: str
    last_completed: datetime | None
    recent_new: int
    ai_pending: int
    running: bool
    in_window: bool


@dataclass(frozen=True, slots=True)
class ScoredSystem:
    system_id: str
    name: str
    score: float
    in_window: bool


def score_system(state: SystemState, now: datetime) -> float:
    if state.last_completed is None:
        return round(NEVER_SCANNED_AGE * 2.0, 2)
    hours = max((now - state.last_completed).total_seconds() / 3600, 0.0)
    urgency = 1.0 + min(state.recent_new, RECENT_DELTA_CAP) * RECENT_DELTA_WEIGHT
    if state.ai_pending:
        urgency += AI_PENDING_BONUS
    return round(hours / CADENCE_HOURS["structure"] * urgency, 2)


def rank_systems(states: Iterable[SystemState], now: datetime) -> list[ScoredSystem]:
    scored = [
        ScoredSystem(s.system_id, s.name, score_system(s, now), s.in_window)
        for s in states
        if not s.running
    ]
    return sorted(scored, key=lambda s: (-s.score, s.system_id))


def select_launches(ranked: Sequence[ScoredSystem], max_parallel: int = MAX_PARALLEL) -> list[str]:
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least 1")
    eligible = [s.system_id for s in ranked if s.in_window and s.score >= LAUNCH_THRESHOLD]
    return eligible[:max_parallel]
