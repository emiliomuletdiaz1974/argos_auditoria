"""Campaign workflows (ARG-007): deterministic and I/O-free; I/O goes into activities."""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import record_in_journal, smoke_probe

RETRY_POLICY = RetryPolicy(
    maximum_attempts=3, backoff_coefficient=2.0, initial_interval=timedelta(milliseconds=200)
)
_TIMEOUT = timedelta(seconds=30)


@workflow.defn
class SmokeCampaign:
    @workflow.run
    async def run(self, systems: list[str]) -> list[dict[str, Any]]:
        workflow_id = workflow.info().workflow_id
        await workflow.execute_activity(
            record_in_journal,
            args=["campaign.smoke.start", {"systems": systems, "workflow_id": workflow_id}],
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        results: list[dict[str, Any]] = []
        for system in systems:
            results.append(
                await workflow.execute_activity(
                    smoke_probe,
                    system,
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=RETRY_POLICY,
                )
            )
        await workflow.execute_activity(
            record_in_journal,
            args=["campaign.smoke.end", {"workflow_id": workflow_id, "probes": len(results)}],
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return results
