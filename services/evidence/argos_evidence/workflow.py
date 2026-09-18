"""The evidence of a sealed campaign, from its verdicts to its credential (ARG-061…068).

Artifacts, Merkle tree, signed root with the journal anchored, time stamp,
dossier and credential, one activity each. The workflow only decides and
waits. If the stamp is not there yet, the dossier says so and a credential is
issued for it; when the stamp arrives, a new dossier and a new credential are
made and the previous credential is revoked as superseded. The earlier dossier
stays in the WORM store.
"""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

TASK_QUEUE = "argos-evidence"
STEP_TIMEOUT = timedelta(minutes=5)
RETRY = RetryPolicy(
    maximum_attempts=5, backoff_coefficient=2.0, initial_interval=timedelta(seconds=1)
)


@workflow.defn
class EvidenceWorkflow:
    async def _step(self, name: str, *args: str) -> Any:
        return await workflow.execute_activity(
            name, args=list(args), start_to_close_timeout=STEP_TIMEOUT, retry_policy=RETRY
        )

    @workflow.run
    async def run(
        self, campaign_id: str, stamp_attempts: int = 12, stamp_wait_seconds: int = 300
    ) -> dict[str, Any]:
        artifacts = await self._step("evidence_write_artifacts", campaign_id)
        await self._step("evidence_build_root", campaign_id)
        await self._step("evidence_sign_root", campaign_id)
        stamp = await self._step("evidence_stamp", campaign_id)
        dossier = await self._step("evidence_write_dossier", campaign_id)
        await self._step("evidence_issue_credential", campaign_id, dossier)

        attempts = 0
        while stamp != "stamped" and attempts < stamp_attempts:
            attempts += 1
            await workflow.sleep(timedelta(seconds=stamp_wait_seconds))
            stamp = await self._step("evidence_stamp", campaign_id)
            if stamp == "stamped":
                dossier = await self._step("evidence_write_dossier", campaign_id)
                await self._step("evidence_issue_credential", campaign_id, dossier)
        return {
            "campaign_id": campaign_id,
            "artifacts": artifacts,
            "dossier": dossier,
            "time_stamp": stamp,
        }
