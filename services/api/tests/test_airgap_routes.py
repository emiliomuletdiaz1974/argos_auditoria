"""ARG-090 · the airlock through the API: scan the medium, export a kind of the closed list."""

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from argos_airgap import Gate
from argos_airgap.importers import tsr_importer, tsr_name
from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator

OBJECT = "campaigns/0192b000-0000-7000-8000-000000000001/root.sig"
ADMIN = {"Authorization": "Bearer platform_admin"}


class Tokens:
    def validate(self, token: str) -> Identity:
        role, _, extra = token.partition(":")
        amr = frozenset({"pwd"} if extra == "nootp" else {"pwd", "otp"})
        return Identity(sub=role, name=role, roles=frozenset({role}), amr=amr)


@pytest.fixture
def gate(tmp_path: Path) -> Gate:
    for folder in ("in", "out", "work"):
        (tmp_path / folder).mkdir()
    recorded: list[Any] = []

    def tsq(folder: Path, params: Any) -> None:
        (folder / "a.tsq").write_bytes(b"query")

    made = Gate(
        tmp_path / "in",
        tmp_path / "out",
        tmp_path / "work",
        importers={"tsr": tsr_importer(lambda: [OBJECT], lambda key, reply: None)},
        exporters={"tsq": tsq},
        record=lambda *entry: recorded.append(entry),
    )
    made.recorded = recorded  # type: ignore[attr-defined]
    return made


def _client(gate: Gate | None) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, Tokens()), airgap=gate))


def test_the_scan_imports_what_verifies_and_says_what_it_refused(gate: Gate) -> None:
    (gate.inbox / tsr_name(OBJECT)).write_bytes(b"reply")
    (gate.inbox / "notes.txt").write_text("hola", encoding="utf-8")
    answer = _client(gate).post(f"{API_PREFIX}/airgap/imports", headers=ADMIN)
    assert answer.status_code == 200, answer.text
    results = {r["file"]: r for r in answer.json()["results"]}
    assert results[tsr_name(OBJECT)]["result"] == "imported"
    assert len(results[tsr_name(OBJECT)]["sha256"]) == 64
    assert results["notes.txt"]["result"] == "rejected"
    actors = {entry[0] for entry in gate.recorded}  # type: ignore[attr-defined]
    assert actors == {"user:platform_admin"}


def test_an_export_of_the_list_is_written_with_its_hashes(gate: Gate) -> None:
    answer = _client(gate).post(f"{API_PREFIX}/airgap/exports", json={"kind": "tsq"}, headers=ADMIN)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["kind"] == "tsq" and body["files"][0]["name"] == "a.tsq"
    assert (gate.outbox / body["id"] / "a.tsq").is_file()


def test_an_export_outside_the_list_is_forbidden_and_recorded(gate: Gate) -> None:
    answer = _client(gate).post(
        f"{API_PREFIX}/airgap/exports", json={"kind": "database"}, headers=ADMIN
    )
    assert answer.status_code == 403
    assert "closed list" in answer.text
    _, action, _, outcome = gate.recorded[-1]  # type: ignore[attr-defined]
    assert (action, outcome) == ("airgap.export", "refused")


@pytest.mark.parametrize("route", ["imports", "exports"])
def test_the_airlock_asks_for_the_second_factor(gate: Gate, route: str) -> None:
    answer = _client(gate).post(
        f"{API_PREFIX}/airgap/{route}",
        json={"kind": "tsq"},
        headers={"Authorization": "Bearer platform_admin:nootp"},
    )
    assert answer.status_code == 401
    assert "insufficient_user_authentication" in answer.headers["www-authenticate"]


@pytest.mark.parametrize("role", ["campaign_manager", "dpo_reviewer", "read_only_auditor"])
def test_only_the_platform_admin_uses_the_airlock(gate: Gate, role: str) -> None:
    headers = {"Authorization": f"Bearer {role}"}
    client = _client(gate)
    assert client.post(f"{API_PREFIX}/airgap/imports", headers=headers).status_code == 403
    exports = client.post(f"{API_PREFIX}/airgap/exports", json={"kind": "tsq"}, headers=headers)
    assert exports.status_code == 403
    assert list(gate.outbox.iterdir()) == []


def test_without_an_airlock_the_api_says_so() -> None:
    assert _client(None).post(f"{API_PREFIX}/airgap/imports", headers=ADMIN).status_code == 503
