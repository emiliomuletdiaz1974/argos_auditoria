"""ARG-047 · the campaign API with real tokens of the development realm."""

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argos_auth import JwtValidator
from argos_challenges.api.app import create_app
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import open_or_recur
from argos_challenges.store import persist_verdict, pin_campaign, request_approval
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration

BASE = os.environ.get("ARGOS_TEST_KEYCLOAK", "http://127.0.0.1:8180")
ISSUER = f"{BASE}/realms/argos"
SYSTEM = "00000000-0000-4000-8000-000000000001"
UNIT: dict[str, Any] = {
    "unit_id": "c" * 64,
    "challenge_id": "sec-encryption-in-transit",
    "challenge_version": "1.0",
    "obligation": "OBL-RGPD-32-3",
    "system_id": SYSTEM,
    "node_key": "k-node-0001",
    "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
    "sampling": None,
    "severity": "high",
}
PROBE = {"ok": True, "data": {"rows": [{"ssl": "off"}]}}


def _token(username: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "argos-tests",
            "username": username,
            "password": "test",  # noqa: S106 - development realm
            "scope": "openid",
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310
        f"{ISSUER}/protocol/openid-connect/token", data=body
    )
    for _ in range(30):
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                return str(json.loads(response.read())["access_token"])
        except OSError:
            time.sleep(2)
    raise RuntimeError("Keycloak did not issue a token")


@pytest.fixture
def api(migrated_db: str) -> TestClient:
    signalled: list[tuple[str, str, str]] = []

    async def signal(campaign_id: str, name: str, argument: str) -> None:
        signalled.append((campaign_id, name, argument))

    client = TestClient(
        create_app(migrated_db, JwtValidator(ISSUER, "argos-api"), signal_campaign=signal)
    )
    client.signalled = signalled  # type: ignore[attr-defined]
    return client


def _headers(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(username)}"}


def test_a_dpo_approves_and_the_journal_says_who(api: TestClient, migrated_db: str) -> None:
    created = api.post(
        "/campaigns", json={"name": "Campaña con Keycloak"}, headers=_headers("manager.test")
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["campaign_id"]
    pin_campaign(
        migrated_db,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    request_approval(migrated_db, campaign_id, "start", {"units": 1})

    gates = api.get(f"/campaigns/{campaign_id}/gates", headers=_headers("dpo.test")).json()
    assert gates == [{"gate": "start", "payload": {"units": 1}, "approvals": 0, "needed": 1}]

    approved = api.post(
        f"/campaigns/{campaign_id}/gates/start/approve", headers=_headers("dpo.test")
    )
    assert approved.json()["state"] == "approved"
    assert api.signalled == [(campaign_id, "approve", "start")]  # type: ignore[attr-defined]

    grants = [
        entry
        for entry in PostgresJournal(migrated_db).read(1, 500)
        if entry.action == "approval.grant"
    ]
    assert grants and grants[-1].actor.startswith("user:")
    assert "start" in grants[-1].payload_canon


def test_a_dpo_cannot_launch_and_a_manager_cannot_approve(api: TestClient) -> None:
    created = api.post(
        "/campaigns", json={"name": "Campaña de roles"}, headers=_headers("manager.test")
    )
    campaign_id = created.json()["campaign_id"]
    launch = api.post(f"/campaigns/{campaign_id}/launch", headers=_headers("dpo.test"))
    assert launch.status_code == 403
    approve = api.post(
        f"/campaigns/{campaign_id}/gates/start/approve", headers=_headers("manager.test")
    )
    assert approve.status_code in (403, 409)


def test_the_findings_and_verdicts_of_a_campaign_are_readable(
    api: TestClient, migrated_db: str
) -> None:
    created = api.post(
        "/campaigns", json={"name": "Campaña con hallazgo"}, headers=_headers("manager.test")
    )
    campaign_id = created.json()["campaign_id"]
    pin_campaign(
        migrated_db,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    unit = {**UNIT, "campaign_id": campaign_id}
    verdict = evaluate(unit, PROBE)
    verdict_id, _ = persist_verdict(migrated_db, campaign_id, unit, verdict)
    finding = open_or_recur(migrated_db, campaign_id, unit, verdict, verdict_id)

    verdicts = api.get(f"/campaigns/{campaign_id}/verdicts", headers=_headers("dpo.test")).json()
    assert [row["result"] for row in verdicts] == ["non_compliant"]
    findings = api.get(f"/campaigns/{campaign_id}/findings", headers=_headers("dpo.test")).json()
    assert [row["id"] for row in findings] == [finding["id"]]

    moved = api.post(
        f"/findings/{finding['id']}/transition",
        json={"to": "in_remediation"},
        headers=_headers("dpo.test"),
    )
    assert moved.json() == {"finding_id": finding["id"], "from": "open", "to": "in_remediation"}
    illegal = api.post(
        f"/findings/{finding['id']}/transition",
        json={"to": "closed_compliant"},
        headers=_headers("dpo.test"),
    )
    assert illegal.status_code == 409


def test_an_unknown_campaign_is_a_404(api: TestClient) -> None:
    missing = api.get(
        "/campaigns/00000000-0000-4000-8000-0000000000ff", headers=_headers("dpo.test")
    )
    assert missing.status_code == 404
