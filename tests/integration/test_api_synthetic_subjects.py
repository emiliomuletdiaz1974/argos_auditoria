"""QA-36 · the synthetic subject can be reached from the API alone (ADR-0008).

The front had no way to create a subject, to learn its id, to read the package the client
injects, or to find the id of an injection it has to confirm: only a development script
registered subjects, so every `authorize` ended in 409 in the bench.
"""

from typing import cast

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import JwtValidator

from .test_api_campaigns import SYSTEM, PersonValidator, Runner, _as, _plan

pytestmark = pytest.mark.integration


@pytest.fixture
def api(migrated_db: str) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=migrated_db, campaign_runner=Runner()))


MANAGER = "campaign_manager"
DPO = "dpo_reviewer"


def _generate(api: TestClient, campaign_id: str, count: int = 1) -> list[str]:
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects",
        json={"count": count},
        headers=_as(MANAGER),
    )
    assert answer.status_code == 201, answer.text
    return [subject["id"] for subject in answer.json()["subjects"]]


def _authorize(api: TestClient, campaign_id: str, subject_id: str) -> str:
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/authorize",
        json={
            "subject_id": subject_id,
            "system_id": SYSTEM,
            "point": "public.patients",
            "method": "alta manual en el sistema del cliente",
            "revert_procedure": "borrado del registro tras el ejercicio",
        },
        headers=_as(DPO, "ana"),
    )
    assert answer.status_code == 201, answer.text
    return str(answer.json()["injection_id"])


def test_the_campaign_manager_generates_the_subjects_once(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña con sujetos")
    path = f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects"
    assert api.post(path, json={"count": 1}, headers=_as(DPO)).status_code == 403
    assert api.post(path, json={"count": 1}, headers=_as("read_only_auditor")).status_code == 403
    assert api.post(path, json={"count": 0}, headers=_as(MANAGER)).status_code == 422
    ids = _generate(api, campaign_id, 2)
    assert len(set(ids)) == 2
    assert api.post(path, json={"count": 1}, headers=_as(MANAGER)).status_code == 409


def test_the_state_of_the_subjects_and_their_injections_is_readable(api: TestClient) -> None:
    campaign_id = _plan(api, "Campaña con estado")
    (subject_id,) = _generate(api, campaign_id)
    injection_id = _authorize(api, campaign_id, subject_id)
    path = f"{API_PREFIX}/campaigns/{campaign_id}/synthetic"
    assert api.get(path, headers=_as("read_only_auditor")).status_code == 403

    state = api.get(path, headers=_as(DPO)).json()
    assert [subject["id"] for subject in state["subjects"]] == [subject_id]
    assert state["injections"] == [
        {
            "id": injection_id,
            "subject_id": subject_id,
            "system_id": SYSTEM,
            "point": "public.patients",
            "state": "authorized",
        }
    ]
    confirmed = api.post(
        f"{API_PREFIX}/synthetic/{injection_id}/confirm-injection", headers=_as(MANAGER)
    )
    assert confirmed.status_code == 200, confirmed.text
    again = api.get(path, headers=_as(MANAGER)).json()
    assert again["injections"][0]["state"] == "injected"


def test_the_client_package_carries_the_values_and_the_injections_to_confirm(
    api: TestClient,
) -> None:
    campaign_id = _plan(api, "Campaña con paquete")
    (subject_id,) = _generate(api, campaign_id)
    injection_id = _authorize(api, campaign_id, subject_id)
    path = f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects/{subject_id}/package"
    assert api.get(path, headers=_as("read_only_auditor")).status_code == 403

    package = api.get(path, headers=_as(MANAGER)).json()
    assert package["subject_id"] == subject_id
    assert package["values"]["email"].endswith("@example.invalid")
    assert package["value_hashes"].keys() == package["values"].keys()
    assert [(i["id"], i["point"]) for i in package["injections"]] == [
        (injection_id, "public.patients")
    ]
    assert package["injections"][0]["revert_procedure"]


def test_a_subject_of_another_campaign_has_no_package_here(api: TestClient) -> None:
    mine, other = _plan(api, "Campaña mía"), _plan(api, "Campaña ajena")
    _generate(api, mine)
    (foreign,) = _generate(api, other)
    path = f"{API_PREFIX}/campaigns/{mine}/synthetic/subjects/{foreign}/package"
    assert api.get(path, headers=_as(MANAGER)).status_code == 404


def test_a_sealed_campaign_takes_no_new_subjects(api: TestClient, migrated_db: str) -> None:
    import psycopg

    campaign_id = _plan(api, "Campaña cerrada")
    with psycopg.connect(migrated_db) as conn:
        conn.execute("UPDATE argos.campaigns SET status = 'sealed' WHERE id = %s", (campaign_id,))
    answer = api.post(
        f"{API_PREFIX}/campaigns/{campaign_id}/synthetic/subjects",
        json={"count": 1},
        headers=_as(MANAGER),
    )
    assert answer.status_code == 409
