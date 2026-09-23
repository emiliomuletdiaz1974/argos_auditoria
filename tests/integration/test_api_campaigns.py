"""ARG-071 y ARG-075 · campaigns over the v1: plan, look before running, launch and approve.

The campaign engine owns the campaign (`argos_challenges.store`) and Temporal runs it; the API is
the door. These tests walk that door: a creation that survives a retry, the literal plan shown
before a single probe, the live progress, and the gates with the double control of ARG-047.
They also carry over what the campaign API of Phase 05 proved with real tokens of the realm.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator
from argos_challenges.store import pin_campaign, request_approval, save_units
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration

BEARER = {"Authorization": "Bearer a-token"}
SYSTEM = "00000000-0000-4000-8000-000000000001"
KEYCLOAK = os.environ.get("ARGOS_TEST_KEYCLOAK", "http://127.0.0.1:8180")
ISSUER = f"{KEYCLOAK}/realms/argos"
UNVERIFIABLE = [
    {
        "challenge_id": "ai-risk-register",
        "connector": None,
        "node_key": "k-node-0002",
        "reason": "the challenge is reserved in the catalog but not written yet",
        "system_id": SYSTEM,
    }
]


def _unit(campaign_id: str) -> dict[str, Any]:
    return {
        "unit_id": "c" * 64,
        "campaign_id": campaign_id,
        "challenge_id": "sec-encryption-in-transit",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": SYSTEM,
        "node_key": "k-node-0001",
        "probe": {
            "kind": "sql",
            "target": "public.patients",
            "statement": "SHOW ssl",
            "params": {},
        },
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None,
        "severity": "high",
    }


class Runner:
    """What the API asks of Temporal, kept in memory."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.signals: list[tuple[str, str, str]] = []
        self.live: dict[str, dict[str, Any]] = {}
        self.remediations: list[dict[str, Any]] = []

    async def remediate(self, scope: dict[str, Any]) -> str:
        self.remediations.append(scope)
        return f"remediation-{len(self.remediations)}"

    async def start(self, campaign_id: str) -> str:
        self.started.append(campaign_id)
        self.live[campaign_id] = {"status": "preparing", "done": 0, "findings": 0}
        return f"campaign-{campaign_id}"

    async def signal(self, campaign_id: str, name: str, argument: str) -> None:
        self.signals.append((campaign_id, name, argument))

    async def progress(self, campaign_id: str) -> dict[str, Any]:
        if campaign_id not in self.live:
            raise LookupError(campaign_id)
        return self.live[campaign_id]


class PersonValidator:
    """Each token names a person and a role: `role:someone`."""

    def validate(self, token: str) -> Identity:
        role, _, person = token.partition(":")
        return Identity(sub=person or role, name=person or role, roles=frozenset({role}))


def _as(role: str, person: str = "") -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{person or role}"}


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def api(migrated_db: str, runner: Runner) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=migrated_db, campaign_runner=runner))


def _journal_rows(dsn: str, injection_id: str) -> list[tuple[str, ...]]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        return [
            tuple(str(value) for value in row)
            for row in conn.execute(
                "SELECT action FROM argos.audit_journal WHERE payload_canon LIKE %s ORDER BY seq",
                (f"%{injection_id}%",),
            ).fetchall()
        ]


def _plan(api: TestClient, name: str, key: str | None = None) -> str:
    headers = {**_as("campaign_manager"), **({"Idempotency-Key": key} if key else {})}
    created = api.post(f"{API_PREFIX}/campaigns", json={"name": name}, headers=headers)
    assert created.status_code == 201, created.text
    return str(created.json()["campaign_id"])


def _prepare(dsn: str, campaign_id: str) -> None:
    """What `prepare_campaign` leaves behind: pinned, compiled and asking the start gate."""
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    save_units(dsn, campaign_id, [_unit(campaign_id)])
    request_approval(dsn, campaign_id, "start", {"units": 1, "unverifiable": UNVERIFIABLE})


def test_a_retried_creation_creates_one_campaign(api: TestClient, migrated_db: str) -> None:
    first = _plan(api, "Campaña reintentada", key="plan-once")
    second = _plan(api, "Campaña reintentada", key="plan-once")
    assert first == second

    listed = api.get(f"{API_PREFIX}/campaigns", params={"limit": 200}, headers=_as("dpo_reviewer"))
    names = [c["name"] for c in listed.json()["items"]]
    assert names.count("Campaña reintentada") == 1


def test_a_campaign_is_listed_and_read(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña para leer")
    page = api.get(f"{API_PREFIX}/campaigns", params={"limit": 1}, headers=_as("read_only_auditor"))
    assert page.status_code == 200
    assert page.json()["items"][0]["id"] == campaign_id

    read = api.get(f"{API_PREFIX}/campaigns/{campaign_id}", headers=_as("read_only_auditor"))
    assert read.status_code == 200
    assert read.json()["status"] == "planned"
    assert read.json()["created_by"] == "user:campaign_manager"

    missing = api.get(
        f"{API_PREFIX}/campaigns/00000000-0000-4000-8000-0000000000ff", headers=_as("dpo_reviewer")
    )
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")


def test_launching_hands_the_campaign_to_temporal(api: TestClient, runner: Runner) -> None:
    campaign_id = _plan(api, "Campaña lanzada")
    launched = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=_as("campaign_manager")
    )
    assert launched.status_code == 200
    assert launched.json()["workflow_id"] == f"campaign-{campaign_id}"
    assert runner.started == [campaign_id]


def test_an_unknown_campaign_is_not_launched(api: TestClient, runner: Runner) -> None:
    launched = api.post(
        f"{API_PREFIX}/campaigns/00000000-0000-4000-8000-0000000000ff/launch",
        headers=_as("campaign_manager"),
    )
    assert launched.status_code == 404
    assert runner.started == []


def test_without_a_runner_nothing_is_launched(migrated_db: str) -> None:
    validator = cast(JwtValidator, PersonValidator())
    client = TestClient(create_app(validator, dsn=migrated_db))
    campaign_id = _plan(client, "Campaña sin Temporal")
    launched = client.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=_as("campaign_manager")
    )
    assert launched.status_code == 503


def test_the_plan_is_shown_before_anything_runs(api: TestClient, migrated_db: str) -> None:
    campaign_id = _plan(api, "Campaña con plan previo")
    early = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/plan", headers=_as("dpo_reviewer"))
    assert early.status_code == 409, "there is no plan until the campaign is prepared"

    _prepare(migrated_db, campaign_id)
    plan = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/plan", headers=_as("dpo_reviewer"))
    assert plan.status_code == 200
    body = plan.json()
    [question] = body["units"]
    assert question["probe"]["statement"] == "SHOW ssl"
    assert question["probe"]["target"] == "public.patients"
    assert question["obligation"] == "OBL-RGPD-32-3"
    assert body["unverifiable"] == UNVERIFIABLE
    assert body["probes_run"] == 0


def test_the_progress_is_the_one_of_the_workflow(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña en marcha")
    before = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/progress", headers=_as("dpo_reviewer"))
    assert before.status_code == 409

    api.post(f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=_as("campaign_manager"))
    live = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/progress", headers=_as("dpo_reviewer"))
    assert live.status_code == 200
    assert live.json()["status"] == "preparing"


def test_a_gate_opens_with_one_approval(api: TestClient, runner: Runner, migrated_db: str) -> None:
    campaign_id = _plan(api, "Campaña con compuerta")
    _prepare(migrated_db, campaign_id)

    gates = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/gates", headers=_as("dpo_reviewer"))
    [start] = gates.json()["items"]
    assert (start["gate"], start["approvals"], start["needed"]) == ("start", 0, 1)

    approved = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve",
        json={"note": "plan revisado"},
        headers=_as("dpo_reviewer", "ana"),
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"
    assert runner.signals == [(campaign_id, "approve", "start")]


def test_the_sampling_gate_needs_two_different_people(
    api: TestClient, runner: Runner, migrated_db: str
) -> None:
    campaign_id = _plan(api, "Campaña con muestreo")
    _prepare(migrated_db, campaign_id)
    request_approval(migrated_db, campaign_id, "sampling", {"units": 1})
    path = f"{API_PREFIX}/campaigns/{campaign_id}/gates/sampling/approve"

    first = api.post(path, json={}, headers=_as("dpo_reviewer", "ana"))
    assert first.json()["state"] == "awaiting_second_approval"
    assert runner.signals == []

    again = api.post(path, json={}, headers=_as("dpo_reviewer", "ana"))
    assert again.status_code == 409, "the same person does not count twice"

    second = api.post(path, json={}, headers=_as("dpo_reviewer", "luis"))
    assert second.json()["state"] == "approved"
    assert runner.signals == [(campaign_id, "approve", "sampling")]


def test_a_gate_that_was_not_asked_cannot_be_approved(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña sin compuerta")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve",
        json={},
        headers=_as("dpo_reviewer"),
    )
    assert answer.status_code == 409


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


def test_with_real_tokens_the_journal_says_who_approved(migrated_db: str, runner: Runner) -> None:
    client = TestClient(
        create_app(JwtValidator(ISSUER, "argos-api"), dsn=migrated_db, campaign_runner=runner)
    )
    manager = {"Authorization": f"Bearer {_token('manager.test')}"}
    dpo = {"Authorization": f"Bearer {_token('dpo.test')}"}

    created = client.post(
        f"{API_PREFIX}/campaigns", json={"name": "Campaña con Keycloak"}, headers=manager
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["campaign_id"]
    _prepare(migrated_db, campaign_id)

    refused = client.post(f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=dpo)
    assert refused.status_code == 403
    approved = client.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve", json={}, headers=dpo
    )
    assert approved.json()["state"] == "approved"

    grants = [e for e in PostgresJournal(migrated_db).read(1) if e.action == "approval.grant"]
    assert grants and grants[-1].actor.startswith("user:")
    assert campaign_id in grants[-1].payload_canon


def test_the_tray_says_who_has_approved_so_far(api: TestClient, migrated_db: str) -> None:
    campaign_id = _plan(api, "Campaña con bandeja")
    _prepare(migrated_db, campaign_id)
    request_approval(migrated_db, campaign_id, "sampling", {"units": 1})
    api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/sampling/approve",
        json={},
        headers=_as("dpo_reviewer", "ana"),
    )
    gates = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/gates", headers=_as("dpo_reviewer"))
    sampling = next(g for g in gates.json()["items"] if g["gate"] == "sampling")
    assert (sampling["approved_by"], sampling["approvals"], sampling["needed"]) == (
        ["user:ana"],
        1,
        2,
    )


# ── What came over from the campaign API of Phase 05 when it was retired (F08-17) ──


def test_the_verdicts_of_a_campaign_are_readable(api: TestClient, migrated_db: str) -> None:
    from argos_challenges.evaluator import evaluate
    from argos_challenges.store import persist_verdict

    campaign_id = _plan(api, "Campaña con veredictos")
    _prepare(migrated_db, campaign_id)
    unit = _unit(campaign_id)
    verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": "off"}]}})
    persist_verdict(migrated_db, campaign_id, unit, verdict, probe_journal_seq=None)

    answer = api.get(
        f"{API_PREFIX}/campaigns/{campaign_id}/verdicts",
        params={"limit": 200},
        headers=_as("read_only_auditor"),
    )
    assert answer.status_code == 200, answer.text
    items = answer.json()["items"]
    assert [(item["challenge_id"], item["result"]) for item in items] == [
        ("sec-encryption-in-transit", "non_compliant")
    ]
    assert len(items[0]["verdict_hash"]) == 64


def test_the_synthetic_subject_is_authorised_by_the_dpo_and_confirmed_by_the_client(
    api: TestClient, migrated_db: str
) -> None:
    from argos_challenges.synthetic import generate_subjects, register_subjects

    campaign_id = _plan(api, "Campaña con sujeto sintético")
    subject = generate_subjects("semilla-f08-17", 1)[0]
    register_subjects(migrated_db, campaign_id, [subject])
    body = {
        "subject_id": subject.id,
        "system_id": SYSTEM,
        "point": "public.patients",
        "method": "alta manual en el sistema del cliente",
        "revert_procedure": "borrado del registro tras el ejercicio",
    }
    path = f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/authorize"

    refused = api.post(path, json=body, headers=_as("campaign_manager"))
    assert refused.status_code == 403, "authorising an injection is the DPO's"

    authorized = api.post(path, json=body, headers=_as("dpo_reviewer", "ana"))
    assert authorized.status_code == 201, authorized.text
    injection_id = authorized.json()["injection_id"]

    confirmations = f"{API_PREFIX}/synthetic/{injection_id}"
    assert (
        api.post(f"{confirmations}/confirm-injection", headers=_as("dpo_reviewer")).status_code
        == 403
    )
    for step, sent in (
        ("confirm-injection", {}),
        (
            "confirm-exercise",
            {
                "right": "erasure",
                "requested_at": "2026-01-10T09:00:00+00:00",
                "answered_at": "2026-01-20T09:00:00+00:00",
            },
        ),
        ("confirm-revert", {}),
    ):
        done = api.post(f"{confirmations}/{step}", json=sent, headers=_as("campaign_manager"))
        assert done.status_code == 200, done.text
    assert done.json()["state"] == "reverted"

    actions = [
        row[0] for row in _journal_rows(migrated_db, injection_id) if row[0].startswith("synthetic")
    ]
    assert actions == [
        "synthetic.authorize",
        "synthetic.injected",
        "synthetic.exercised",
        "synthetic.revert",
    ]


def test_an_injection_without_a_revert_procedure_is_refused(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña sin vuelta atrás")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/authorize",
        json={
            "subject_id": "00000000-0000-4000-8000-0000000000aa",
            "system_id": SYSTEM,
            "point": "public.patients",
            "method": "alta manual",
            "revert_procedure": "   ",
        },
        headers=_as("dpo_reviewer"),
    )
    assert answer.status_code == 422, answer.text


def test_a_remediation_run_is_asked_for_by_the_manager(api: TestClient, runner: Runner) -> None:
    campaign_id = _plan(api, "Campaña a subsanar")
    path = f"{API_PREFIX}/campaigns/{campaign_id}/remediation"

    refused = api.post(path, headers=_as("dpo_reviewer"))
    assert refused.status_code == 403

    started = api.post(path, headers=_as("campaign_manager", "marta"))
    assert started.status_code == 202, started.text
    assert started.json()["workflow_id"]
    assert runner.remediations == [{"campaign_id": campaign_id, "requested_by": "user:marta"}]
