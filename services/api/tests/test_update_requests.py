"""ARG-086 · POST /api/v1/system/updates: verify with the pinned key, then queue (F09-10)."""

import json
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.routers.system import UpdateRequests
from argos_auth import Identity, JwtValidator
from argos_updater.testing import public_key, signed_bundle

KEY = Ed25519PrivateKey.generate()
ADMIN = {"Authorization": "Bearer admin"}


class Admin:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="admin", name="admin", roles=frozenset({"platform_admin"}),
            amr=frozenset({"pwd", "otp"}),
        )  # fmt: skip


@pytest.fixture
def updates(tmp_path: Path) -> UpdateRequests:
    base = tmp_path / "update"
    (base / "inbox").mkdir(parents=True)
    (base / "version").write_text("0.1.0", encoding="utf-8")
    return UpdateRequests(base / "inbox", base / "queue", base, public_key(KEY))


def _client(updates: UpdateRequests | None) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, Admin()), updates=updates))


def _post(client: TestClient, bundle: str) -> object:
    return client.post(f"{API_PREFIX}/system/updates", json={"bundle": bundle}, headers=ADMIN)


def test_a_verified_bundle_is_queued_for_the_updater(updates: UpdateRequests) -> None:
    signed_bundle(updates.inbox, "0.2.0", KEY, ["argos-example"])
    answer = _client(updates).post(
        f"{API_PREFIX}/system/updates", json={"bundle": "bundle-0.2.0"}, headers=ADMIN
    )
    assert answer.status_code == 202, answer.text
    assert answer.json()["version"] == "0.2.0"
    [queued] = list(updates.queue.glob("*.json"))
    request = json.loads(queued.read_text(encoding="utf-8"))
    assert request == {
        "bundle": "bundle-0.2.0",
        "version": "0.2.0",
        "allow_downgrade": False,
        "requested_by": "user:admin",
    }


def test_a_bundle_signed_with_another_key_is_not_queued(updates: UpdateRequests) -> None:
    signed_bundle(updates.inbox, "0.2.0", Ed25519PrivateKey.generate(), ["argos-example"])
    answer = _client(updates).post(
        f"{API_PREFIX}/system/updates", json={"bundle": "bundle-0.2.0"}, headers=ADMIN
    )
    assert answer.status_code == 422
    assert not updates.queue.exists() or not list(updates.queue.glob("*.json"))


def test_an_older_version_is_not_queued(updates: UpdateRequests) -> None:
    signed_bundle(updates.inbox, "0.0.9", KEY, ["argos-example"])
    answer = _client(updates).post(
        f"{API_PREFIX}/system/updates", json={"bundle": "bundle-0.0.9"}, headers=ADMIN
    )
    assert answer.status_code == 422
    assert "older" in answer.text


@pytest.mark.parametrize("name", ["../etc", "bundle/../../x", ".hidden", "a b"])
def test_a_name_that_leaves_the_inbox_is_refused(updates: UpdateRequests, name: str) -> None:
    answer = _client(updates).post(
        f"{API_PREFIX}/system/updates", json={"bundle": name}, headers=ADMIN
    )
    assert answer.status_code == 422


def test_a_bundle_that_is_not_in_the_inbox_is_a_404(updates: UpdateRequests) -> None:
    answer = _client(updates).post(
        f"{API_PREFIX}/system/updates", json={"bundle": "bundle-9.9.9"}, headers=ADMIN
    )
    assert answer.status_code == 404


def test_without_the_updater_configured_the_api_says_so() -> None:
    answer = _client(None).post(
        f"{API_PREFIX}/system/updates", json={"bundle": "bundle-0.2.0"}, headers=ADMIN
    )
    assert answer.status_code == 503
