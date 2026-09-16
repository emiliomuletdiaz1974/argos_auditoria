"""Rescan workflows (ARG-030): deterministic and I/O-free; I/O lives in InventoryActivities."""

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from argos_inventory.scheduler.activities import InventoryActivities, ScanOutcome
    from argos_inventory.scheduler.policy import MAX_PARALLEL, select_launches

QUICK_RETRY = RetryPolicy(
    maximum_attempts=3, initial_interval=timedelta(seconds=1), backoff_coefficient=2.0
)
SINGLE_ATTEMPT = RetryPolicy(maximum_attempts=1)  # a failed scan is a failed run, retried next hour
WAIT_FOR_INGESTION = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=40,
)
SHORT_TIMEOUT = timedelta(minutes=2)
SCAN_TIMEOUT = timedelta(hours=2)
ANALYSIS_TIMEOUT = timedelta(minutes=30)


@workflow.defn
class ScanSystem:
    @workflow.run
    async def run(self, system_id: str) -> dict[str, Any]:
        run_id = str(workflow.uuid4())
        scan: ScanOutcome = await workflow.execute_activity_method(
            InventoryActivities.run_scan,
            args=[system_id, run_id],
            start_to_close_timeout=SCAN_TIMEOUT,
            retry_policy=SINGLE_ATTEMPT,
        )
        result: dict[str, Any] = {
            "system_id": system_id,
            "run_id": run_id,
            "status": scan.status,
            "events": scan.events,
        }
        if scan.status != "completed":
            result["error"] = scan.error
            return result
        result["deltas"] = await workflow.execute_activity_method(
            InventoryActivities.compute_run_deltas,
            args=[system_id, run_id],
            start_to_close_timeout=SHORT_TIMEOUT,
            retry_policy=WAIT_FOR_INGESTION,
        )
        result["analysis"] = await workflow.execute_activity_method(
            InventoryActivities.analyze_system,
            system_id,
            start_to_close_timeout=ANALYSIS_TIMEOUT,
            retry_policy=QUICK_RETRY,
        )
        return result


@workflow.defn
class RescanPlanner:
    @workflow.run
    async def run(self, max_parallel: int = MAX_PARALLEL) -> dict[str, Any]:
        ranked = await workflow.execute_activity_method(
            InventoryActivities.score_systems,
            start_to_close_timeout=SHORT_TIMEOUT,
            retry_policy=QUICK_RETRY,
        )
        chosen = select_launches(ranked, max_parallel)
        scans = await asyncio.gather(*(self._scan(system_id) for system_id in chosen))
        refresh = None
        if chosen:
            refresh = await workflow.execute_activity_method(
                InventoryActivities.refresh_inventory,
                start_to_close_timeout=ANALYSIS_TIMEOUT,
                retry_policy=QUICK_RETRY,
            )
        return {"launched": len(chosen), "scans": list(scans), "refresh": refresh}

    async def _scan(self, system_id: str) -> dict[str, Any]:
        info = workflow.info()
        try:
            result: dict[str, Any] = await workflow.execute_child_workflow(
                ScanSystem.run,
                system_id,
                id=f"{info.workflow_id}-scan-{system_id}",
                task_queue=info.task_queue,
            )
        except ChildWorkflowError as exc:  # one failing system must not hide the others
            return {"system_id": system_id, "status": "error", "error": str(exc.cause or exc)}
        return result
