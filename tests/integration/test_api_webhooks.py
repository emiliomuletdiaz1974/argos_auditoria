"""ARG-079 · webhooks towards the client's ITSM: subscriptions, signed deliveries and their inbox.

«Did it reach the ServiceNow?» is answered from the console: every attempt is recorded. The secret
of a subscription is chosen by the client, kept in the secret store and never comes back: not in a
response, not in the database, not in the journal. The receiver here checks the signature the way
the documentation tells a client to, and the retries are the real ones, run by Temporal.
"""

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
import uuid
from typing import Any, cast

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from temporalio.client import Client
from temporalio.worker import Worker

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.webhooks.dispatch import WebhookActivities
from argos_api.webhooks.store import enqueue_event
from argos_api.webhooks.subscriber import on_event
from argos_api.webhooks.workflow import WebhookDelivery
from argos_auth import Identity, JwtValidator
from argos_common.config import get_config
from argos_common.secret_stores import VaultSecretStore

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
SECRET = "the-client-chose-this-secret-" + uuid.uuid4().hex


class PersonValidator:
    def validate(self, token: str) -> Identity:
        return Identity(sub=token, name=token, roles=frozenset({token}))


def _as(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}


def _public(_host: str) -> list[str]:
    """The example domains of these tests do not resolve: they stand for a public ITSM."""
    return ["93.184.216.34"]


def _secrets() -> VaultSecretStore:
    return VaultSecretStore(VAULT, "root")


def _api(dsn: str) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(
        create_app(validator, dsn=dsn, webhook_secrets=_secrets(), webhook_resolve=_public)
    )


def _subscribe(
    api: TestClient, template: str = "servicenow", events: list[str] | None = None
) -> str:
    created = api.post(
        f"{API_PREFIX}/webhooks",
        json={
            "url": "https://itsm.client.example/api/now/table/incident",
            "events": events or ["finding_opened"],
            "template": template,
            "secret": SECRET,
        },
        headers=_as("platform_admin"),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


class Receiver:
    """The ITSM of the client: checks the signature as documented, fails the first `failures`."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.received: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        header = request.headers["X-Argos-Signature"]
        parts = dict(item.split("=", 1) for item in header.split(","))
        mac = hmac.new(
            SECRET.encode(), parts["t"].encode() + b"." + request.content, hashlib.sha256
        )
        if not hmac.compare_digest(mac.hexdigest(), parts["v1"]):
            return httpx.Response(401)
        if self.failures > 0:
            self.failures -= 1
            return httpx.Response(503)
        self.received.append(json.loads(request.content))
        return httpx.Response(201)


async def _deliver(dsn: str, receiver: Receiver, delivery_id: str, attempts: int) -> str:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    queue = f"argos-webhooks-test-{uuid.uuid4().hex[:8]}"
    activities = WebhookActivities(
        dsn, _secrets(), transport=httpx.MockTransport(receiver), resolve=_public
    )
    async with Worker(
        client, task_queue=queue, workflows=[WebhookDelivery], activities=activities.all()
    ):
        result: str = await client.execute_workflow(
            WebhookDelivery.run,
            args=[delivery_id, attempts, 0.2],
            id=f"webhook-test-{uuid.uuid4().hex[:8]}",
            task_queue=queue,
            execution_timeout=dt.timedelta(minutes=2),
        )
    return result


def test_the_secret_never_comes_back(migrated_db: str) -> None:
    api = _api(migrated_db)
    webhook_id = _subscribe(api)

    listed = api.get(f"{API_PREFIX}/webhooks", headers=_as("platform_admin"))
    assert listed.status_code == 200
    assert webhook_id in [item["id"] for item in listed.json()["items"]]
    assert SECRET not in listed.text

    with psycopg.connect(migrated_db) as conn:
        dumped = conn.execute("SELECT row_to_json(w)::text FROM argos.webhooks w").fetchall()
        journal = conn.execute(
            "SELECT payload_canon FROM argos.audit_journal WHERE payload_canon LIKE %s",
            (f"%{SECRET}%",),
        ).fetchall()
    assert all(SECRET not in row[0] for row in dumped)
    assert journal == []
    assert _secrets().read(f"webhooks/{webhook_id}")["secret"] == SECRET


def test_an_unknown_template_is_refused_at_subscription(migrated_db: str) -> None:
    answer = _api(migrated_db).post(
        f"{API_PREFIX}/webhooks",
        json={
            "url": "https://x.example/hook",
            "events": ["finding_opened"],
            "template": "remedy",
            "secret": SECRET,
        },
        headers=_as("platform_admin"),
    )
    assert answer.status_code == 422


def test_only_the_platform_admin_touches_the_integrations(migrated_db: str) -> None:
    api = _api(migrated_db)
    for role in ("dpo_reviewer", "read_only_auditor", "campaign_manager"):
        assert api.get(f"{API_PREFIX}/webhooks", headers=_as(role)).status_code == 403


def test_an_event_becomes_one_delivery_per_subscription_to_it(migrated_db: str) -> None:
    api = _api(migrated_db)
    wanted = _subscribe(api, events=["finding_opened"])
    other = _subscribe(api, events=["campaign_sealed"])
    created = enqueue_event(
        migrated_db, "finding_opened", {"finding_id": "f-1", "severity": "high"}
    )
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT webhook_id::text FROM argos.webhook_deliveries WHERE id::text = ANY(%s)",
            (created,),
        ).fetchall()
    targets = {row[0] for row in rows}
    assert wanted in targets and other not in targets


def test_a_delivery_is_retried_until_it_arrives_and_the_inbox_says_how(migrated_db: str) -> None:
    api = _api(migrated_db)
    webhook_id = _subscribe(api)
    [delivery_id] = [
        d
        for d in enqueue_event(
            migrated_db,
            "finding_opened",
            {"finding_id": "f-2", "challenge_id": "sec-encryption-at-rest", "severity": "critical"},
        )
        if _owner(migrated_db, d) == webhook_id
    ]
    receiver = Receiver(failures=2)
    assert asyncio.run(_deliver(migrated_db, receiver, delivery_id, attempts=5)) == "delivered"
    [incident] = receiver.received
    assert incident["urgency"] == 1 and "sec-encryption-at-rest" in incident["short_description"]

    inbox = api.get(
        f"{API_PREFIX}/webhooks/{webhook_id}/deliveries", headers=_as("platform_admin")
    ).json()["items"]
    [entry] = [item for item in inbox if item["id"] == delivery_id]
    assert (entry["status"], entry["attempts"], entry["last_status_code"]) == ("delivered", 3, 201)


def test_a_delivery_that_never_arrives_ends_failed_and_says_so(migrated_db: str) -> None:
    api = _api(migrated_db)
    webhook_id = _subscribe(api)
    [delivery_id] = [
        d
        for d in enqueue_event(migrated_db, "finding_opened", {"finding_id": "f-3"})
        if _owner(migrated_db, d) == webhook_id
    ]
    assert asyncio.run(_deliver(migrated_db, Receiver(failures=99), delivery_id, attempts=3)) == (
        "failed"
    )
    inbox = api.get(
        f"{API_PREFIX}/webhooks/{webhook_id}/deliveries", headers=_as("platform_admin")
    ).json()["items"]
    [entry] = [item for item in inbox if item["id"] == delivery_id]
    assert (entry["status"], entry["attempts"], entry["last_status_code"]) == ("failed", 3, 503)


def test_the_bus_turns_a_finding_into_deliveries_and_starts_them(migrated_db: str) -> None:
    api = _api(migrated_db)
    webhook_id = _subscribe(api)
    started: list[str] = []

    async def start(delivery_id: str) -> None:
        started.append(delivery_id)

    handle = on_event("argos.challenge.finding_opened", migrated_db, start)
    asyncio.run(handle({"finding_id": "f-4", "severity": "medium"}, {}))
    assert any(_owner(migrated_db, d) == webhook_id for d in started)


def _owner(dsn: str, delivery_id: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT webhook_id::text FROM argos.webhook_deliveries WHERE id::text = %s",
            (delivery_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, subject: str, event_type: str, data: dict[str, Any]) -> int:
        self.published.append((subject, event_type, data))
        return len(self.published)


def test_a_gate_awaiting_approval_is_announced_once(migrated_db: str) -> None:
    from argos_challenges.activities import ChallengeActivities
    from argos_challenges.store import create_campaign

    from .inventory_helpers import secret_store

    bus = RecordingBus()
    activities = ChallengeActivities(migrated_db, secret_store(), bus=bus)
    campaign_id = create_campaign(migrated_db, "Campaña con aviso", {}, "user:campaign_manager")
    request = {"campaign_id": campaign_id, "gate": "sampling", "payload": {"units": 3}}
    asyncio.run(activities.request_approval(request))
    asyncio.run(activities.request_approval(request))

    [(subject, _, data)] = bus.published
    assert subject == "argos.campaign.approval_requested"
    assert data == {"campaign_id": campaign_id, "gate": "sampling", "approvals_needed": 2}


def test_a_name_that_now_resolves_inside_is_not_delivered_and_says_why(migrated_db: str) -> None:
    """SEC-031: checked again at delivery, and the inbox keeps the kind of error, not its text."""
    api = _api(migrated_db)
    webhook_id = _subscribe(api)
    [delivery_id] = [
        d
        for d in enqueue_event(migrated_db, "finding_opened", {"finding_id": "f-5"})
        if _owner(migrated_db, d) == webhook_id
    ]
    reached: list[httpx.Request] = []

    def receiver(request: httpx.Request) -> httpx.Response:
        reached.append(request)
        return httpx.Response(200)

    activities = WebhookActivities(
        migrated_db,
        _secrets(),
        transport=httpx.MockTransport(receiver),
        resolve=lambda _host: ["10.0.0.9"],
    )
    assert activities.deliver_now(delivery_id) == "failed"
    assert reached == []
    inbox = api.get(
        f"{API_PREFIX}/webhooks/{webhook_id}/deliveries", headers=_as("platform_admin")
    ).json()["items"]
    [entry] = [item for item in inbox if item["id"] == delivery_id]
    assert (entry["status"], entry["last_error"]) == ("failed", "destination_refused")
