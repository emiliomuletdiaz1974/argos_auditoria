"""ARG-007 · smoke workflow against the make dev Temporal server."""

import os
import uuid

import pytest
from temporalio.client import Client, WorkflowFailureError

from argos_challenges.worker import create_worker
from argos_challenges.workflows import SmokeCampaign
from argos_common.config import get_config
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration
TEMPORAL = os.environ.get("ARGOS_TEST_TEMPORAL", "127.0.0.1:7233")


async def test_smoke_campaign_with_retries_and_journal(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", migrated_db)
    get_config.cache_clear()
    client = await Client.connect(TEMPORAL, namespace="default")
    task_queue = f"argos-campaigns-test-{uuid.uuid4().hex[:8]}"

    async with await create_worker(client, task_queue):
        result = await client.execute_workflow(
            SmokeCampaign.run,
            ["his-1", "fail-pacs"],
            id=f"smoke-{uuid.uuid4()}",
            task_queue=task_queue,
        )

    assert [r["system"] for r in result] == ["his-1", "fail-pacs"]
    assert result[0]["attempts"] == 1
    assert result[1]["attempts"] == 3
    journal = PostgresJournal(migrated_db)
    actions = [e.action for e in journal.read()]
    assert actions[-2:] == ["campaign.smoke.start", "campaign.smoke.end"]
    assert journal.verify().intact
    get_config.cache_clear()


async def test_exhausted_retries_fail_the_workflow(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", migrated_db)
    get_config.cache_clear()
    client = await Client.connect(TEMPORAL, namespace="default")
    task_queue = f"argos-campaigns-test-{uuid.uuid4().hex[:8]}"
    async with await create_worker(client, task_queue):
        with pytest.raises(WorkflowFailureError):
            await client.execute_workflow(
                SmokeCampaign.run,
                ["always-fail"],
                id=f"smoke-{uuid.uuid4()}",
                task_queue=task_queue,
            )
    get_config.cache_clear()
