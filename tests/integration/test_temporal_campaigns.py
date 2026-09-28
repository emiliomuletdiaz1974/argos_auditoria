"""Quality review QA-01, QA-063 · what Temporal really answers reaches the API as a reason.

The route tests hand in a runner in memory; this one is the runner the API uses in production,
against the Temporal of the development environment and a task queue no worker listens to: the
workflows are started and never run, which is enough to meet the real errors.
"""

import asyncio
import uuid

import pytest
from temporalio.client import Client

from argos_api.main import TemporalCampaigns
from argos_api.runner import AlreadyRunningError
from argos_common.config import get_config

pytestmark = pytest.mark.integration


def _runner() -> TemporalCampaigns:
    return TemporalCampaigns(get_config().TEMPORAL_ADDRESS, queue=f"no-worker-{uuid.uuid4().hex}")


async def _terminate(*workflow_ids: str) -> None:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    for workflow_id in workflow_ids:
        await client.get_workflow_handle(workflow_id).terminate("test cleanup")


def test_the_progress_of_a_campaign_never_launched_is_a_lookup_error() -> None:
    with pytest.raises(LookupError):
        asyncio.run(_runner().progress(str(uuid.uuid4())))


def test_launching_a_running_campaign_again_is_already_running() -> None:
    runner, campaign = _runner(), str(uuid.uuid4())
    workflow_id = asyncio.run(runner.start(campaign))
    try:
        with pytest.raises(AlreadyRunningError):
            asyncio.run(runner.start(campaign))
    finally:
        asyncio.run(_terminate(workflow_id))


def test_a_second_verification_while_the_first_runs_is_already_running() -> None:
    runner, scope = _runner(), {"finding_id": str(uuid.uuid4()), "requested_by": "user:x"}
    workflow_id = asyncio.run(runner.remediate(scope))
    try:
        with pytest.raises(AlreadyRunningError):
            asyncio.run(runner.remediate(scope))
    finally:
        asyncio.run(_terminate(workflow_id))
