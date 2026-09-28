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


# --- Quality review QA-01: QA-006, QA-061 -------------------------------------------------------


class StartsOnly:
    """A runner that starts and leaves the campaign as it was, as Temporal does before its worker
    takes the workflow: the campaign is still `planned` right after its launch."""

    def __init__(self) -> None:
        self.started: list[str] = []

    async def start(self, campaign_id: str) -> str:
        from argos_api.runner import AlreadyRunningError

        if campaign_id in self.started:
            raise AlreadyRunningError(f"the campaign {campaign_id} is already running")
        self.started.append(campaign_id)
        return f"campaign-{campaign_id}"


def _launching(dsn: str, runner: StartsOnly) -> TestClient:
    app = create_app(
        cast(JwtValidator, Tokens()),
        dsn=dsn,
        size_limits=("S", TWO_SYSTEMS),
        campaign_runner=runner,
    )
    return TestClient(app)


MANAGER = {"Authorization": "Bearer campaign_manager"}


def test_a_campaign_just_launched_takes_its_place_at_once(migrated_db: str) -> None:
    """QA-006: launched one after the other, the second is refused while the first still has no
    gate request: a launched campaign counts from the launch."""
    from argos_challenges.store import create_campaign

    runner = StartsOnly()
    client = _launching(migrated_db, runner)
    first, second = (create_campaign(migrated_db, f"C{n}", {}, "user:m") for n in (1, 2))
    assert client.post(f"{API_PREFIX}/campaigns/{first}/launch", headers=MANAGER).status_code == 200
    refused = client.post(f"{API_PREFIX}/campaigns/{second}/launch", headers=MANAGER)
    assert refused.status_code == 409, refused.text
    assert "campañas en paralelo" in refused.json()["detail"]
    assert runner.started == [first]


def test_launching_again_a_campaign_that_holds_its_place_is_a_state_error(migrated_db: str) -> None:
    """QA-061: at the limit, launching the same campaign again says it is already running, not
    that the size is full (it already holds its own place)."""
    from argos_challenges.store import create_campaign

    runner = StartsOnly()
    client = _launching(migrated_db, runner)
    only = create_campaign(migrated_db, "C1", {}, "user:m")
    assert client.post(f"{API_PREFIX}/campaigns/{only}/launch", headers=MANAGER).status_code == 200
    again = client.post(f"{API_PREFIX}/campaigns/{only}/launch", headers=MANAGER)
    assert again.status_code == 409
    assert "already running" in again.json()["detail"]


def test_two_registrations_at_once_do_not_exceed_the_size(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-061: measuring and registering are one step; two at once cannot both see room."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from argos_common import capacity

    slow = capacity.measure

    def measured_slowly(dsn: str) -> dict[str, int]:
        found = slow(dsn)
        time.sleep(0.5)
        return found

    monkeypatch.setattr(capacity, "measure", measured_slowly)
    client = _client(migrated_db)
    with ThreadPoolExecutor(max_workers=3) as pool:
        answers = list(
            pool.map(
                lambda n: client.post(
                    f"{API_PREFIX}/systems", json=_system(f"hr-{n}"), headers=ADMIN
                ),
                range(3),
            )
        )
    assert sorted(a.status_code for a in answers) == [201, 201, 409]
