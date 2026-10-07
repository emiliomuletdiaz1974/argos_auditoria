"""QA-36 · accepted risks expire by themselves: something has to ask, and keep asking."""

import asyncio

import pytest

from argos_challenges.worker import expire_periodically


@pytest.mark.asyncio
async def test_the_expiry_runs_at_start_and_again_after_a_failure() -> None:
    calls: list[int] = []

    def expire() -> list[str]:
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("the database was not there")
        return ["f1"] if len(calls) == 2 else []

    task = asyncio.create_task(expire_periodically(expire, interval=0.01))
    for _ in range(200):
        if len(calls) >= 4:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 4, "a failed round does not stop the next ones"
