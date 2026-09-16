"""ARG-030 · rescan policy and the thread-safe publisher bridge."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from argos_inventory.scheduler.activities import ThreadSafePublisher
from argos_inventory.scheduler.policy import (
    MAX_PARALLEL,
    ScoredSystem,
    SystemState,
    rank_systems,
    score_system,
    select_launches,
)

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _state(
    system_id: str = "s1",
    hours_ago: float | None = 48,
    recent_new: int = 0,
    ai_pending: int = 0,
    running: bool = False,
    in_window: bool = True,
) -> SystemState:
    last = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return SystemState(
        system_id, system_id, "rdbms", last, recent_new, ai_pending, running, in_window
    )


def test_never_scanned_systems_come_first() -> None:
    assert score_system(_state(hours_ago=None), NOW) == 1998.0


@pytest.mark.parametrize(
    ("hours_ago", "recent_new", "ai_pending", "expected"),
    [
        (12, 0, 0, 0.5),
        (48, 0, 0, 2.0),
        (48, 3, 0, 3.2),
        (48, 50, 0, 4.0),
        (48, 0, 2, 3.0),
        (-1, 0, 0, 0.0),
    ],
)
def test_score_follows_age_and_urgency(
    hours_ago: float, recent_new: int, ai_pending: int, expected: float
) -> None:
    state = _state(hours_ago=hours_ago, recent_new=recent_new, ai_pending=ai_pending)
    assert score_system(state, NOW) == expected


def test_ranking_skips_running_scans_and_orders_by_score_then_id() -> None:
    states = [
        _state("b", hours_ago=48),
        _state("a", hours_ago=48),
        _state("c", hours_ago=None, running=True),
        _state("d", hours_ago=None),
    ]
    assert [s.system_id for s in rank_systems(states, NOW)] == ["d", "a", "b"]


def test_launches_respect_window_threshold_and_parallelism() -> None:
    ranked = [
        ScoredSystem("never", "never", 1998.0, True),
        ScoredSystem("closed", "closed", 900.0, False),
        *(ScoredSystem(f"due-{i}", f"due-{i}", 5.0 - i * 0.1, True) for i in range(6)),
        ScoredSystem("fresh", "fresh", 0.4, True),
    ]
    assert select_launches(ranked) == ["never", "due-0", "due-1", "due-2"]
    assert len(select_launches(ranked, MAX_PARALLEL + 10)) == 7
    assert select_launches([ScoredSystem("fresh", "fresh", 0.99, True)]) == []
    with pytest.raises(ValueError, match="max_parallel"):
        select_launches(ranked, 0)


async def test_thread_safe_publisher_publishes_on_the_owning_loop() -> None:
    loop = asyncio.get_running_loop()
    seen: list[asyncio.AbstractEventLoop] = []

    class LoopBus:
        async def publish(
            self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
        ) -> int:
            seen.append(asyncio.get_running_loop())
            return 7

    publisher = ThreadSafePublisher(LoopBus(), loop)

    def from_worker_thread() -> int:
        return asyncio.run(
            publisher.publish("argos.discovery.delta_ready", "discovery.delta_ready.v1", {})
        )

    assert await asyncio.to_thread(from_worker_thread) == 7
    assert seen == [loop]
