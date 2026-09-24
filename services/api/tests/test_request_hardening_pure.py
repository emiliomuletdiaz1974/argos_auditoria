"""The hardening of the campaign API from the 2026-09-18 audit, carried to the single API."""

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from argos_api.app import create_app
from argos_api.routers import campaigns
from argos_auth import Identity, JwtValidator

BEARER = {"Authorization": "Bearer a-token"}
PROBLEM = "application/problem+json"
UNREACHABLE = "postgresql://argos@127.0.0.1:1/argos?connect_timeout=1"


class Holding:
    """A person with the given roles; never planning and approving at once (F09-24)."""

    def __init__(self, roles: frozenset[str]) -> None:
        self._roles = roles

    def validate(self, token: str) -> Identity:
        return Identity(
            sub="someone", name="Someone", roles=self._roles, amr=frozenset({"pwd", "otp"})
        )


REVIEWER = frozenset({"platform_admin", "dpo_reviewer", "read_only_auditor"})
MANAGER = frozenset({"campaign_manager"})


def _client(roles: frozenset[str] = REVIEWER, **kwargs: Any) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, Holding(roles)), **kwargs))


def test_the_route_map_is_not_published_unless_asked() -> None:
    client = _client()
    for path in ("/api/v1/docs", "/api/v1/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_the_route_map_is_published_in_development() -> None:
    client = _client(publish_docs=True)
    assert client.get("/api/v1/openapi.json").status_code == 200
    assert client.get("/api/v1/docs").status_code == 200


def test_a_store_that_does_not_answer_is_a_503_without_its_message() -> None:
    response = _client(dsn=UNREACHABLE).get(f"/api/v1/campaigns/{uuid4()}", headers=BEARER)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith(PROBLEM)
    assert "127.0.0.1" not in response.text
    assert "connection" not in response.text.lower()


def test_a_scope_of_megabytes_is_refused() -> None:
    scope = {"systems": ["x" * 100] * 200}
    response = _client(MANAGER).post(
        "/api/v1/campaigns", json={"name": "Grande", "scope": scope}, headers=BEARER
    )
    assert response.status_code == 422
    assert "scope" in response.json()["detail"]


@pytest.mark.parametrize("field", ["point", "method", "revert_procedure"])
def test_free_text_of_an_injection_is_bounded(field: str) -> None:
    body = {
        "subject_id": str(uuid4()),
        "system_id": str(uuid4()),
        "point": "tabla patients",
        "method": "alta manual",
        "revert_procedure": "baja manual",
    }
    body[field] = "x" * 2_001
    response = _client().post(
        f"/api/v1/campaigns/{uuid4()}/synthetic/authorize", json=body, headers=BEARER
    )
    assert response.status_code == 422
    assert field in response.json()["detail"]


def test_the_note_of_a_transition_is_bounded() -> None:
    response = _client().post(
        f"/api/v1/findings/{uuid4()}/transition",
        json={"to": "in_remediation", "note": "x" * 2_001},
        headers=BEARER,
    )
    assert response.status_code == 422


def test_a_gate_name_that_is_not_a_gate_is_refused() -> None:
    response = _client().post(
        f"/api/v1/campaigns/{uuid4()}/gates/{'a' * 40}/approve", json={}, headers=BEARER
    )
    assert response.status_code == 422


def test_the_authorisation_is_bound_to_the_campaign_of_the_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def authorize(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return str(uuid4())

    monkeypatch.setattr(campaigns, "_record", lambda dsn, campaign_id: {})
    monkeypatch.setattr(campaigns, "authorize_injection", authorize)
    campaign_id = str(uuid4())
    response = _client(dsn=UNREACHABLE).post(
        f"/api/v1/campaigns/{campaign_id}/synthetic/authorize",
        json={
            "subject_id": str(uuid4()),
            "system_id": str(uuid4()),
            "point": "tabla patients",
            "method": "alta manual",
            "revert_procedure": "baja manual",
        },
        headers=BEARER,
    )
    assert seen.get("campaign_id") == campaign_id, response.text


@pytest.mark.parametrize("days", [-1, 0, 400, 5 * 365])
def test_a_risk_is_accepted_for_a_future_bounded_time(days: int) -> None:
    """SEC-042: no acceptance in the past, and none for ever (12 months at most by default)."""
    from datetime import date, timedelta

    expiry = (date.today() + timedelta(days=days)).isoformat()
    response = _client().post(
        f"/api/v1/findings/{uuid4()}/transition",
        json={
            "to": "risk_accepted",
            "note": "Riesgo asumido por la dirección",
            "risk_expiry": expiry,
        },
        headers=BEARER,
    )
    assert response.status_code == 422, days
    assert "risk_expiry" in response.json()["detail"]
