"""The workflow of one delivery: only Temporal here, so its sandbox can run it (ARG-079).

The attempt itself —signing, sending, recording— is the activity in `dispatch`; this only decides
how often to try: exponential backoff until it arrives or runs out of attempts.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

TASK_QUEUE = "argos-webhooks"
MAX_ATTEMPTS = 8  # 1, 2, 4… seconds apart with the default interval: about four minutes in all
TIMEOUT_SECONDS = 15.0


@workflow.defn
class WebhookDelivery:
    """One delivery, retried with exponential backoff until it arrives or runs out of attempts."""

    @workflow.run
    async def run(
        self, delivery_id: str, max_attempts: int = MAX_ATTEMPTS, first_wait: float = 1.0
    ) -> str:
        result: str = await workflow.execute_activity(
            "deliver_webhook",
            args=[delivery_id, max_attempts],
            start_to_close_timeout=timedelta(seconds=TIMEOUT_SECONDS * 2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=first_wait),
                backoff_coefficient=2.0,
                maximum_attempts=max_attempts,
            ),
        )
        return result
