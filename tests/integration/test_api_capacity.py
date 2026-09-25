"""ARG-098 · the API refuses honestly what exceeds the size, and reports the position (F10-08).

`POST /systems` registers a system unless the size is full; launching a campaign is refused when
the parallel campaigns are at their limit; `GET /operations/capacity` gives the bands and the local
series. A refusal is a `409` with the figures and the options, not an error of the server.
"""

from typing import cast

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator

pytestmark = pytest.mark.integration

TWO_SYSTEMS = {"systems": 2, "assets": 1000, "parallel_campaigns": 1, "ai_tokens_per_day": 1000}


class Tokens:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub=token, name=token, roles=frozenset({token}), amr=frozenset({"pwd", "otp"})
        )


def _client(dsn: str) -> TestClient:
    app = create_app(cast(JwtValidator, Tokens()), dsn=dsn, size_limits=("S", TWO_SYSTEMS))
    return TestClient(app)


def _system(name: str) -> dict[str, object]:
    return {
        "name": name,
        "kind": "rdbms",
        "environment": "production",
        "connector": "argos_sql.postgres:PostgresConnector",
        "config": {"statement_timeout_ms": 5000},
    }


ADMIN = {"Authorization": "Bearer platform_admin"}


def test_a_system_is_registered_until_the_size_is_full(migrated_db: str) -> None:
    client = _client(migrated_db)
    for n in (1, 2):
        created = client.post(f"{API_PREFIX}/systems", json=_system(f"hr-{n}"), headers=ADMIN)
        assert created.status_code == 201, created.text
        assert created.json()["secret"] == f"connectors/{created.json()['id']}"
    refused = client.post(f"{API_PREFIX}/systems", json=_system("hr-3"), headers=ADMIN)
    assert refused.status_code == 409
    problem = refused.json()
    assert "La talla S admite 2" in problem["detail"]
    assert "ampliar la talla" in problem["detail"]


def test_an_unknown_connector_is_refused(migrated_db: str) -> None:
    body = {**_system("x"), "connector": "os:system"}
    answer = _client(migrated_db).post(f"{API_PREFIX}/systems", json=body, headers=ADMIN)
    assert answer.status_code == 422


def test_the_capacity_report_has_the_bands_and_the_series(migrated_db: str) -> None:
    client = _client(migrated_db)
    client.post(f"{API_PREFIX}/systems", json=_system("hr-1"), headers=ADMIN)
    report = client.get(f"{API_PREFIX}/operations/capacity", headers=ADMIN).json()
    rows = {row["dimension"]: row for row in report["usage"]}
    assert rows["systems"] == {
        "dimension": "systems",
        "used": 1,
        "limit": 2,
        "ratio": 0.5,
        "band": "green",
        "size": "S",
    }
    assert report["size"] == "S"
    assert report["history"] == []


def test_only_the_administrator_registers_systems(migrated_db: str) -> None:
    for role in ("campaign_manager", "dpo_reviewer", "read_only_auditor"):
        answer = _client(migrated_db).post(
            f"{API_PREFIX}/systems", json=_system("x"), headers={"Authorization": f"Bearer {role}"}
        )
        assert answer.status_code == 403, role
