"""ARG-071 · the API is one container of the development environment, and it serves no page.

The v1 answers under `/api/v1` (ADR-0012). The front end is its own application, on its own
origin (ARG-073): the image neither builds nor mounts the console of phase 08, and a path outside
the API is a 404 in problem+json. The deliveries towards the ITSM run in their own process.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

from argos_api import API_PREFIX
from argos_common.config import get_config

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "services" / "api" / "Dockerfile"
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
BASE = "http://127.0.0.1:8000"
WEBHOOK_QUEUE = "argos-webhooks"


def _get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as answer:  # noqa: S310
            return answer.status, answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode("utf-8", "replace")


def test_the_container_answers_its_health_check() -> None:
    status, body = _get("/health")
    assert status == 200
    assert json.loads(body)["service"] == "argos-api"


def test_the_container_serves_no_page() -> None:
    for path in ("/", "/campaigns"):
        status, body = _get(path)
        assert status == 404, path
        assert json.loads(body)["status"] == 404, "a path outside the API is a problem too"


def test_the_v1_is_mounted_and_asks_for_a_token() -> None:
    status, body = _get(f"{API_PREFIX}/campaigns")
    assert status == 401
    assert json.loads(body)["status"] == 401, "errors are problem+json, also here"


def test_the_contract_the_front_end_reads_is_the_one_it_serves() -> None:
    status, body = _get(f"{API_PREFIX}/openapi.json")
    assert status == 200
    served = json.loads(body)
    kept = json.loads((REPO / "services" / "api" / "openapi.json").read_text(encoding="utf-8"))
    # The graph is mounted only when there is a database, so it is in the served document and not
    # in the generated one; everything else has to match, or the published contract is stale.
    assert sorted(set(served["paths"]) - {f"{API_PREFIX}/inventory/graph"}) == sorted(kept["paths"])


@pytest.mark.asyncio
async def test_the_webhook_worker_polls_its_queue() -> None:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    described = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace="default",
            task_queue=TaskQueue(name=WEBHOOK_QUEUE),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    assert described.pollers, "no worker is polling argos-webhooks"


def test_the_image_builds_no_front_end_and_drops_privileges() -> None:
    recipe = DOCKERFILE.read_text(encoding="utf-8")
    assert "node" not in recipe and "npm" not in recipe, "the API image carries no console"
    users = re.findall(r"^USER\s+(\S+)", recipe, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}


def test_the_image_carries_no_secrets() -> None:
    forbidden = re.compile(r"^(ENV|ARG)\s+\S*(TOKEN|PASSWORD|SECRET|KEY)", re.MULTILINE)
    assert not forbidden.search(DOCKERFILE.read_text(encoding="utf-8"))


def test_both_processes_are_declared_in_the_development_compose() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    for service in ("api", "webhook-worker"):
        assert re.search(rf"^  {service}:$", compose, re.MULTILINE), service
