"""ARG-071 · the refusals of folder 03 (campaigns and gates) carry their code and speak Spanish."""

from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.runner import AlreadyRunningError
from argos_auth import JwtValidator
from argos_challenges.store import request_approval

from .test_api_campaigns import PersonValidator, Runner, _as, _plan, _prepare

pytestmark = pytest.mark.integration

UNKNOWN = "00000000-0000-4000-8000-0000000000ff"


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def api(migrated_db: str, runner: Runner) -> TestClient:
    return TestClient(
        create_app(cast(JwtValidator, PersonValidator()), dsn=migrated_db, campaign_runner=runner)
    )


def _problem(answer: Any, status: int, code: str) -> str:
    body = answer.json()
    assert answer.status_code == status, body
    assert body["code"] == code, body
    return str(body["detail"])


def test_an_unknown_campaign_is_campaign_not_found(api: TestClient) -> None:
    answer = api.get(f"{API_PREFIX}/campaigns/{UNKNOWN}", headers=_as("dpo_reviewer"))
    assert _problem(answer, 404, "campaign_not_found") == f"La campaña {UNKNOWN} no existe."


def test_without_a_runner_the_launch_is_campaign_runner_unavailable(migrated_db: str) -> None:
    client = TestClient(create_app(cast(JwtValidator, PersonValidator()), dsn=migrated_db))
    campaign_id = _plan(client, "Campaña sin motor de errores")
    answer = client.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=_as("campaign_manager")
    )
    _problem(answer, 503, "campaign_runner_unavailable")


def test_the_plan_before_preparing_is_campaign_plan_not_ready(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña sin plan aún")
    answer = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/plan", headers=_as("dpo_reviewer"))
    assert "Lance la campaña" in _problem(answer, 409, "campaign_plan_not_ready")


def test_progress_before_launching_is_campaign_not_running(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña parada")
    answer = api.get(f"{API_PREFIX}/campaigns/{campaign_id}/progress", headers=_as("dpo_reviewer"))
    _problem(answer, 409, "campaign_not_running")


def test_launching_twice_is_campaign_already_running(api: TestClient, runner: Runner) -> None:
    async def busy(campaign_id: str) -> str:
        raise AlreadyRunningError(f"the campaign {campaign_id} is already running")

    runner.start = busy  # type: ignore[method-assign]
    campaign_id = _plan(api, "Campaña lanzada dos veces")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/launch", headers=_as("campaign_manager")
    )
    assert "ya está en marcha" in _problem(answer, 409, "campaign_already_running")


def test_a_remediation_running_is_remediation_already_running(
    api: TestClient, runner: Runner
) -> None:
    async def busy(scope: dict[str, Any]) -> str:
        raise AlreadyRunningError("the re-run is still going")

    runner.remediate = busy  # type: ignore[method-assign]
    campaign_id = _plan(api, "Campaña con reejecución en curso")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/remediation", headers=_as("campaign_manager")
    )
    _problem(answer, 409, "remediation_already_running")


def test_a_gate_not_requested_is_gate_not_requested(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña sin compuerta pedida")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve",
        json={},
        headers=_as("dpo_reviewer", "ana"),
    )
    detail = _problem(answer, 409, "gate_not_requested")
    assert detail == "La compuerta «Inicio de la campaña» no se ha solicitado."


def test_approving_twice_is_gate_already_approved(api: TestClient, migrated_db: str) -> None:
    campaign_id = _plan(api, "Campaña aprobada dos veces")
    _prepare(migrated_db, campaign_id)
    request_approval(migrated_db, campaign_id, "sampling", {"units": 1})
    path = f"{API_PREFIX}/campaigns/{campaign_id}/gates/sampling/approve"
    api.post(path, json={}, headers=_as("dpo_reviewer", "ana"))
    answer = api.post(path, json={}, headers=_as("dpo_reviewer", "ana"))
    assert "otra persona" in _problem(answer, 409, "gate_already_approved")


def test_who_created_the_campaign_does_not_approve_it(api: TestClient, migrated_db: str) -> None:
    created = api.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Campaña de Eva"},
        headers=_as("campaign_manager", "eva"),
    )
    campaign_id = created.json()["campaign_id"]
    _prepare(migrated_db, campaign_id)
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve",
        json={},
        headers=_as("dpo_reviewer", "eva"),
    )
    assert _problem(answer, 409, "same_person_approval") == (
        "Quien creó la campaña no puede aprobarla: hace falta otra persona."
    )


def test_a_sealed_campaign_is_campaign_closed(api: TestClient, migrated_db: str) -> None:
    campaign_id = _plan(api, "Campaña sellada")
    _prepare(migrated_db, campaign_id)
    with psycopg.connect(migrated_db) as conn:
        conn.execute("UPDATE argos.campaigns SET status = 'sealed' WHERE id = %s", (campaign_id,))
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/gates/start/approve",
        json={},
        headers=_as("dpo_reviewer", "ana"),
    )
    assert _problem(answer, 409, "campaign_closed") == (
        "La campaña está sellada y no admite más aprobaciones."
    )


def test_an_unknown_subject_is_synthetic_subject_not_found(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña sin sujetos")
    answer = api.get(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects/{UNKNOWN}/package",
        headers=_as("dpo_reviewer"),
    )
    _problem(answer, 404, "synthetic_subject_not_found")


def test_generating_twice_is_synthetic_subjects_already_generated(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña con sujetos")
    path = f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects"
    first = api.post(path, json={"count": 1}, headers=_as("campaign_manager"))
    assert first.status_code == 201, first.text
    answer = api.post(path, json={"count": 1}, headers=_as("campaign_manager"))
    _problem(answer, 409, "synthetic_subjects_already_generated")


def test_a_subject_of_another_campaign_is_synthetic_subject_not_in_campaign(
    api: TestClient,
) -> None:
    other = _plan(api, "Campaña dueña del sujeto")
    made = api.post(
        f"{API_PREFIX}/campaigns/{other}/synthetic/subjects",
        json={"count": 1},
        headers=_as("campaign_manager"),
    )
    subject_id = made.json()["subjects"][0]["id"]
    campaign_id = _plan(api, "Campaña ajena al sujeto")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/authorize",
        json={
            "subject_id": subject_id,
            "system_id": "00000000-0000-4000-8000-000000000001",
            "point": "tabla de pacientes",
            "method": "alta manual",
            "revert_procedure": "baja manual",
        },
        headers=_as("dpo_reviewer"),
    )
    _problem(answer, 409, "synthetic_subject_not_in_campaign")


def test_the_validators_of_the_body_speak_spanish(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña con cuerpo inválido")
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/authorize",
        json={
            "subject_id": UNKNOWN,
            "system_id": UNKNOWN,
            "point": "p",
            "method": "m",
            "revert_procedure": "   ",
        },
        headers=_as("dpo_reviewer"),
    )
    detail = _problem(answer, 422, "invalid_request")
    assert "procedimiento para revertirla" in detail
    big = api.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Grande", "scope": {"x": "y" * 70000}},
        headers=_as("campaign_manager"),
    )
    assert "El alcance ocupa más de" in _problem(big, 422, "invalid_request")
