"""ARG-043/047 · the campaign worker and API run as containers of the development environment."""

import json
import re
import urllib.request
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
HEALTH = "http://127.0.0.1:8003/health"


def test_the_api_container_answers_its_health_check() -> None:
    with urllib.request.urlopen(HEALTH, timeout=10) as response:  # noqa: S310 - fixed localhost
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok", "service": TASK_QUEUE}


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


@pytest.mark.parametrize("service", ["challenge-worker", "challenge-api"])
def test_both_services_are_declared_in_the_development_compose(service: str) -> None:
    assert re.search(rf"^  {service}:$", COMPOSE.read_text(encoding="utf-8"), re.MULTILINE)
