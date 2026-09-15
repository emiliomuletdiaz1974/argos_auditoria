"""Campaign domain activities (ARG-007): I/O lives here, never in the workflow."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from argos_common.config import get_config
from argos_common.journal_pg import PostgresJournal


@activity.defn
async def smoke_probe(system: str) -> dict[str, Any]:
    """Exercise the worker -> activity -> result chain.

    Smoke workflow only: `fail-*` fails on the first two attempts and `always-fail` on every
    attempt, so the retry policy is exercised without mocks.
    """
    attempt = activity.info().attempt
    if system == "always-fail" or (system.startswith("fail-") and attempt < 3):
        raise RuntimeError(f"simulated smoke failure on attempt {attempt}")
    return {
        "system": system,
        "ok": True,
        "attempts": attempt,
        "at": datetime.now(UTC).isoformat(),
    }


@activity.defn
async def record_in_journal(action: str, payload: dict[str, Any]) -> int:
    journal = PostgresJournal(get_config().DATABASE_URL)
    actor = f"system:worker:{activity.info().task_queue}"
    return await asyncio.to_thread(journal.append, actor, action, payload)
