"""ARG-043 · the campaign worker runs as a container of the development environment.

Its API is gone: since F08-17 the routes are those of the single API (`tests/integration/
test_api_containers.py`), served from one container with the console.
"""

import re
from pathlib import Path

import pytest
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

from argos_common.config import get_config

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "services" / "challenge-engine" / "Dockerfile"
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
TASK_QUEUE = "argos-campaigns"


@pytest.mark.asyncio
async def test_the_worker_container_polls_the_campaign_queue() -> None:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    described = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace="default",
            task_queue=TaskQueue(name=TASK_QUEUE),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    assert described.pollers, "no worker is polling argos-campaigns"


def test_the_image_does_not_run_as_root() -> None:
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)
    assert users, "the Dockerfile must drop privileges with USER"
    assert users[-1] not in {"root", "0"}


def test_the_image_carries_no_secrets() -> None:
    forbidden = re.compile(r"^(ENV|ARG)\s+\S*(TOKEN|PASSWORD|SECRET|KEY)", re.MULTILINE)
    assert not forbidden.search(DOCKERFILE.read_text(encoding="utf-8"))


def test_the_worker_is_declared_in_the_development_compose() -> None:
    assert re.search(r"^  challenge-worker:$", COMPOSE.read_text(encoding="utf-8"), re.MULTILINE)


def test_the_campaign_api_is_gone_from_the_development_compose() -> None:
    """Its routes live in the single API since F08-17; two doors would be two stories."""
    assert "challenge-api" not in COMPOSE.read_text(encoding="utf-8")
