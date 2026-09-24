"""ARG-088 · the diagnostic package through the API: request, review, then encrypt (F09-11)."""

import datetime as dt
from pathlib import Path
from typing import cast

import pyrage
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.routers.support import SupportDiagnostics
from argos_auth import Identity, JwtValidator
from argos_support import DiagnosticsStore, collect, open_package
from argos_support.testing import FakeInspector, service

ADMIN = {"Authorization": "Bearer platform_admin"}
IDENTITY = pyrage.x25519.Identity.generate()
BASE = f"{API_PREFIX}/support/diagnostics"


class Tokens:
    """The token is the role; `nootp` signs in without the second factor."""

    def validate(self, token: str) -> Identity:
        role, _, extra = token.partition(":")
        amr = frozenset({"pwd"} if extra == "nootp" else {"pwd", "otp"})
        return Identity(sub=role, name=role, roles=frozenset({role}), amr=amr)


@pytest.fixture
def support(tmp_path: Path) -> SupportDiagnostics:
    return SupportDiagnostics(DiagnosticsStore(tmp_path), str(IDENTITY.to_public()))


def _client(support: SupportDiagnostics | None) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, Tokens()), support=support))


def _ready(support: SupportDiagnostics) -> str:
    ident = support.store.request("user:platform_admin")
    inspector = FakeInspector([service("api")], logs={"api": "started 99992001F\n"})
    preview = collect(inspector, lambda n: [], "0.1.0", dt.datetime(2026, 9, 24, tzinfo=dt.UTC))
    support.store.save(ident, preview)
    return ident


def test_a_request_is_queued_for_the_collector(support: SupportDiagnostics) -> None:
    answer = _client(support).post(BASE, headers=ADMIN)
    assert answer.status_code == 202, answer.text
    ident = answer.json()["id"]
    assert answer.json()["status"] == "collecting"
    assert support.store.pending() == [ident]
    assert _client(support).get(f"{BASE}/{ident}", headers=ADMIN).json()["status"] == "collecting"


def test_the_preview_shows_the_index_and_every_file_in_clear(support: SupportDiagnostics) -> None:
    ident = _ready(support)
    body = _client(support).get(f"{BASE}/{ident}", headers=ADMIN).json()
    assert body["status"] == "ready"
    preview = support.store.load(ident)
    assert body["index_sha256"] == preview.index_sha256
    assert body["index"]["note"].startswith("Paquete de diagnóstico")
    shown = {f["name"]: f["content"] for f in body["files"]}
    assert set(shown) == set(preview.files)
    assert shown["logs/api.log"] == preview.files["logs/api.log"].decode("utf-8")
    assert "99992001F" not in shown["logs/api.log"]


def test_the_package_is_what_was_reviewed(support: SupportDiagnostics) -> None:
    ident = _ready(support)
    sha = _client(support).get(f"{BASE}/{ident}", headers=ADMIN).json()["index_sha256"]
    answer = _client(support).post(
        f"{BASE}/{ident}/package", json={"approved_index_sha256": sha}, headers=ADMIN
    )
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "application/octet-stream"
    assert f"argos-diagnostics-{ident}.tar.gz.age" in answer.headers["content-disposition"]
    preview = support.store.load(ident)
    assert open_package(answer.content, str(IDENTITY)) == {
        **preview.files,
        "INDEX.json": preview.index,
    }


def test_another_index_or_an_edited_file_gives_no_package(support: SupportDiagnostics) -> None:
    ident = _ready(support)
    client = _client(support)
    answer = client.post(
        f"{BASE}/{ident}/package", json={"approved_index_sha256": "a" * 64}, headers=ADMIN
    )
    assert answer.status_code == 422
    sha = client.get(f"{BASE}/{ident}", headers=ADMIN).json()["index_sha256"]
    (support.store.previews / ident / "events.txt").write_text("edited", encoding="utf-8")
    answer = client.post(
        f"{BASE}/{ident}/package", json={"approved_index_sha256": sha}, headers=ADMIN
    )
    assert answer.status_code == 422


def test_a_preview_still_collecting_or_unknown_has_no_package(support: SupportDiagnostics) -> None:
    client = _client(support)
    ident = client.post(BASE, headers=ADMIN).json()["id"]
    body = {"approved_index_sha256": "a" * 64}
    assert client.post(f"{BASE}/{ident}/package", json=body, headers=ADMIN).status_code == 409
    assert client.get(f"{BASE}/0000000000-00000000", headers=ADMIN).status_code == 404
    assert client.get(f"{BASE}/..%2Fsecrets", headers=ADMIN).status_code in {404, 422}


@pytest.mark.parametrize("role", ["campaign_manager", "dpo_reviewer", "read_only_auditor"])
def test_only_the_platform_admin_asks_for_diagnostics(
    support: SupportDiagnostics, role: str
) -> None:
    client = _client(support)
    headers = {"Authorization": f"Bearer {role}"}
    assert client.post(BASE, headers=headers).status_code == 403
    ident = _ready(support)
    assert client.get(f"{BASE}/{ident}", headers=headers).status_code == 403


def test_the_package_asks_for_the_second_factor(support: SupportDiagnostics) -> None:
    ident = _ready(support)
    answer = _client(support).post(
        f"{BASE}/{ident}/package",
        json={"approved_index_sha256": "a" * 64},
        headers={"Authorization": "Bearer platform_admin:nootp"},
    )
    assert answer.status_code == 401
    assert "insufficient_user_authentication" in answer.headers["www-authenticate"]


def test_without_a_configured_store_the_api_says_so() -> None:
    assert _client(None).post(BASE, headers=ADMIN).status_code == 503
