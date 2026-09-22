"""ARG-072 · the authorisation matrix, checked against a hand-written expectation.

`tests/fixtures/authz_matrix.yaml` says who should be able to do what; this suite walks **every**
role by **every** permission over the real application. The two files are written apart on purpose:
if the matrix the API enforces drifts from the RACI of the contract, the difference shows up here.
"""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import AUTHENTICATED, create_app
from argos_api.authz import PERMISSIONS, PermissionGuard
from argos_api.routers import session
from argos_auth import ROLES, Identity, JwtValidator

REPO = Path(__file__).resolve().parents[2]
EXPECTED: dict[str, dict[str, bool]] = yaml.safe_load(
    (REPO / "tests" / "fixtures" / "authz_matrix.yaml").read_text(encoding="utf-8")
)
# Open by design (ADR-0013): there is no access token yet when a session opens or refreshes.
OPEN_ROUTES = {("POST", "/api/v1/auth/refresh"), ("POST", "/api/v1/auth/session")}
READING = ".read"
BEARER = {"Authorization": "Bearer a-token"}


class RoleValidator:
    """A token of exactly one realm role: what the matrix is written in terms of."""

    def __init__(self, role: str) -> None:
        self._role = role

    def validate(self, token: str) -> Identity:
        return Identity(sub=self._role, name=self._role, roles=frozenset({self._role}))


def _client(role: str) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, RoleValidator(role))))


def _routes() -> list[tuple[str, str, str | None]]:
    """Every route of the v1 as (method, path, permission it demands or None)."""
    found: list[tuple[str, str, str | None]] = []
    for router in (*AUTHENTICATED, session.router):
        for route in router.routes:
            assert isinstance(route, APIRoute)
            guards = [
                dependency.dependency.permission
                for dependency in route.dependencies
                if isinstance(dependency.dependency, PermissionGuard)
            ]
            for method in sorted(route.methods):
                if method != "HEAD":
                    found.append((method, API_PREFIX + route.path, guards[0] if guards else None))
    return found


def _one_route_per_permission() -> dict[str, tuple[str, str]]:
    sample: dict[str, tuple[str, str]] = {}
    for method, path, permission in _routes():
        if permission is not None:
            sample.setdefault(permission, (method, path))
    return sample


def _call(client: TestClient, method: str, path: str) -> Any:
    concrete = path.replace("{campaign_id}", "c-1").replace("{finding_id}", "f-1")
    concrete = concrete.replace("{node_key}", "n-1").replace("{credential_id}", "cr-1")
    concrete = concrete.replace("{verdict_id}", "v-1").replace("{webhook_id}", "w-1")
    concrete = concrete.replace("{gate}", "sampling")
    return client.request(method, concrete, headers=BEARER)


def test_the_expectation_covers_every_role_and_every_permission() -> None:
    assert set(EXPECTED) == set(ROLES)
    for role, granted in EXPECTED.items():
        assert set(granted) == set(PERMISSIONS), role


@pytest.mark.parametrize("role", sorted(ROLES))
def test_every_combination_of_role_and_permission_behaves_as_written(role: str) -> None:
    client = _client(role)
    sample = _one_route_per_permission()
    assert set(sample) == set(PERMISSIONS), "every declared permission needs a route"

    for permission, (method, path) in sorted(sample.items()):
        response = _call(client, method, path)
        allowed = EXPECTED[role][permission]
        if allowed:
            assert response.status_code != 403, (role, permission, method, path)
        else:
            assert response.status_code == 403, (role, permission, method, path)
            assert response.headers["content-type"].startswith("application/problem+json")


def test_no_route_of_the_v1_is_left_without_a_declared_permission() -> None:
    without = {(method, path) for method, path, permission in _routes() if permission is None}
    assert without == OPEN_ROUTES


def test_an_auditor_never_holds_a_permission_that_changes_anything() -> None:
    auditor = {p for p, allowed in EXPECTED["read_only_auditor"].items() if allowed}
    assert all(permission.endswith(READING) for permission in auditor)


def test_whoever_runs_a_campaign_does_not_bless_its_result() -> None:
    assert not EXPECTED["campaign_manager"]["campaigns.approve"]
    assert not EXPECTED["campaign_manager"]["findings.transition"]
    assert not EXPECTED["platform_admin"]["campaigns.approve"]
    assert not EXPECTED["platform_admin"]["findings.transition"]


def test_accepting_a_risk_asks_for_a_reason() -> None:
    response = _client("dpo_reviewer").post(
        "/api/v1/findings/f-1/transition",
        json={"to": "risk_accepted", "note": ""},
        headers=BEARER,
    )
    assert response.status_code == 422
    assert "note" in response.json()["detail"]
