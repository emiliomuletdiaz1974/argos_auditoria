"""ARG-071/073 · the API and the console are one container of the development environment.

One image, one origin (ADR-0012, ADR-0013): the v1 answers under `/api/v1` and the console is
served from the same place, as static files built into the image. Nothing is fetched from a CDN,
because the appliance has no way out. The deliveries towards the ITSM run in their own process.
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
EXTERNAL = re.compile(r"src=\"https?://|href=\"https?://")


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


def test_the_console_is_served_from_the_same_container() -> None:
    status, page = _get("/")
    assert status == 200
    assert '<div id="root">' in page
    assert not EXTERNAL.search(page), "the appliance has no internet: nothing comes from a CDN"


def test_a_console_route_survives_a_reload() -> None:
    status, page = _get("/campaigns")
    assert (status, '<div id="root">' in page) == (200, True)


def test_the_v1_is_mounted_and_asks_for_a_token() -> None:
    status, body = _get(f"{API_PREFIX}/campaigns")
    assert status == 401
    assert json.loads(body)["status"] == 401, "errors are problem+json, also here"


def test_the_contract_the_console_was_built_against_is_the_one_it_serves() -> None:
    status, body = _get(f"{API_PREFIX}/openapi.json")
    assert status == 200
    served = json.loads(body)
    kept = json.loads((REPO / "services" / "api" / "openapi.json").read_text(encoding="utf-8"))
    # The graph is mounted only when there is a database, so it is in the served document and not
    # in the generated one; everything else has to match, or the console types are stale.
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


def test_the_image_builds_the_console_and_drops_privileges() -> None:
    recipe = DOCKERFILE.read_text(encoding="utf-8")
    assert "npm ci" in recipe and "npm run build" in recipe, "the console is built in the image"
    users = re.findall(r"^USER\s+(\S+)", recipe, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}


def test_the_image_carries_no_secrets() -> None:
    forbidden = re.compile(r"^(ENV|ARG)\s+\S*(TOKEN|PASSWORD|SECRET|KEY)", re.MULTILINE)
    assert not forbidden.search(DOCKERFILE.read_text(encoding="utf-8"))


def test_both_processes_are_declared_in_the_development_compose() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    for service in ("api", "webhook-worker"):
        assert re.search(rf"^  {service}:$", compose, re.MULTILINE), service
