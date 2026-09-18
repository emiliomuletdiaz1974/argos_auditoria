"""NATS and OPA answer only to known identities, and each identity only what it needs (M6, M7).

The inventory builds the graph from what arrives on argos.discovery.>, and OPA decides verdicts:
an anonymous client on the network must not be able to write either.
"""

import asyncio
import os
from typing import Any

import httpx
import nats
import pytest
from nats.errors import NoServersError

from argos_events import Bus

pytestmark = pytest.mark.integration

NATS_HOST = os.environ.get("ARGOS_TEST_NATS_HOST", "127.0.0.1:4222")
OPA = os.environ.get("ARGOS_TEST_OPA", "http://127.0.0.1:8181")
USERS = {
    "inventory": "dev-only-nats-inventory",
    "challenge": "dev-only-nats-challenge",
    "argos-dev": "dev-only-nats-host",
}
OPA_TOKEN = "dev-only-opa-host"
VERDICT = f"{OPA}/v1/data/argos/retention/verdict"
# Harmless even against a server without authentication: the ingest ignores this event type, and
# the probe policy is outside argos.* and removed afterwards.
PROBE_SUBJECT = "argos.discovery.auth_probe"
PROBE_TYPE = "discovery.auth_probe.v1"
PROBE_POLICY = "/v1/policies/auth_probe"


def _bus(user: str, password: str | None = None) -> Bus:
    secret = USERS[user] if password is None else password
    return Bus(f"auth-test-{user}", f"nats://{NATS_HOST}", user=user, password=secret)


async def _publish(bus: Bus, subject: str) -> int:
    await bus.connect()
    try:
        return await asyncio.wait_for(bus.publish(subject, PROBE_TYPE, {}), 5)
    finally:
        await bus.close()


async def _connect_once(**credentials: str) -> Any:
    """One attempt, no reconnection: a refused identity must fail, not retry forever."""

    async def quiet(error: Exception) -> None:
        return None

    connection = nats.connect(
        f"nats://{NATS_HOST}",
        allow_reconnect=False,
        max_reconnect_attempts=0,
        connect_timeout=2,
        error_cb=quiet,
        **credentials,
    )
    return await asyncio.wait_for(connection, 10)


@pytest.mark.parametrize(
    "credentials",
    [{}, {"user": "inventory", "password": "guess"}, {"user": "nobody", "password": "x"}],
)
def test_an_unknown_identity_is_not_let_in(credentials: dict[str, str]) -> None:
    with pytest.raises((NoServersError, nats.errors.Error, OSError, TimeoutError)):
        asyncio.run(_connect_once(**credentials))


def test_the_inventory_publishes_discovery_events() -> None:
    assert asyncio.run(_publish(_bus("inventory"), PROBE_SUBJECT)) > 0


def test_another_service_cannot_forge_discovery_events() -> None:
    # A discovery event rewrites the graph the campaigns select from.
    with pytest.raises(Exception):  # noqa: B017 - a denial surfaces as a timeout or an error
        asyncio.run(_publish(_bus("challenge"), PROBE_SUBJECT))


def test_each_service_publishes_on_its_own_subjects() -> None:
    assert asyncio.run(_publish(_bus("challenge"), "argos.challenge.auth_probe")) > 0


def test_the_inventory_consumes_discovery_with_a_durable_consumer() -> None:
    # What the ingest does: its permissions must cover creating the consumer and acknowledging.
    received: list[str] = []

    async def run() -> None:
        consumer = _bus("inventory")
        await consumer.connect()
        try:

            async def handle(data: dict[str, Any], event: dict[str, Any]) -> None:
                received.append(str(event["type"]))

            await consumer.subscribe(PROBE_SUBJECT, durable="auth-probe", handler=handle)
            await _publish(_bus("inventory"), PROBE_SUBJECT)
            for _ in range(50):
                if received:
                    return
                await asyncio.sleep(0.1)
        finally:
            await consumer.close()

    asyncio.run(run())
    assert f"eu.argos.{PROBE_TYPE}" in received


def _refused(response: httpx.Response) -> bool:
    """OPA answers 401 whenever its own authorization policy says no, token or not."""
    return response.status_code == 401 and "administrative policy" in response.text


def test_liveness_needs_no_token() -> None:
    assert httpx.get(f"{OPA}/health", timeout=5).status_code == 200


def test_opa_does_not_evaluate_for_an_anonymous_client() -> None:
    response = httpx.post(VERDICT, json={"input": {}}, timeout=5)
    assert response.status_code == 401


def test_opa_evaluates_for_a_known_token() -> None:
    headers = {"Authorization": f"Bearer {OPA_TOKEN}"}
    response = httpx.post(VERDICT, json={"input": {}}, headers=headers, timeout=5)
    assert response.status_code == 200


def test_even_a_known_client_cannot_load_a_policy() -> None:
    # Loading Rego is how a verdict would be decided from outside; policies come from a
    # read-only mount of the library.
    headers = {"Authorization": f"Bearer {OPA_TOKEN}"}
    try:
        response = httpx.put(
            f"{OPA}{PROBE_POLICY}", content="package auth_probe\nx := 1", headers=headers, timeout=5
        )
        assert _refused(response)
    finally:
        httpx.delete(f"{OPA}{PROBE_POLICY}", headers=headers, timeout=5)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/policies"),
        ("GET", "/v1/data/opa_clients"),
        ("POST", "/v1/data/system/authz/allow"),
    ],
)
def test_even_a_known_client_cannot_read_outside_argos(method: str, path: str) -> None:
    headers = {"Authorization": f"Bearer {OPA_TOKEN}"}
    response = httpx.request(method, f"{OPA}{path}", headers=headers, timeout=5)
    assert _refused(response)
