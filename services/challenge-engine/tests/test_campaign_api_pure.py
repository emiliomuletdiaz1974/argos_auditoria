"""ARG-047 · roles, gates and double control of the campaign API, with a fake validator."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from argos_auth import AuthError, Identity
from argos_challenges.api.app import create_app
from argos_challenges.store import DOUBLE_CONTROL_GATES

MANAGER = Identity(sub="manager", name="Manager", roles=frozenset({"campaign_manager"}))
REVIEWER = Identity(sub="dpo", name="DPO", roles=frozenset({"dpo_reviewer"}))
SECOND_REVIEWER = Identity(sub="dpo-2", name="DPO 2", roles=frozenset({"dpo_reviewer"}))
AUDITOR = Identity(sub="auditor", name="Auditor", roles=frozenset({"read_only_auditor"}))
STRANGER = Identity(sub="none", name="Nobody", roles=frozenset())
CAMPAIGN = "01920000-0000-7000-8000-0000000000c1"


class FakeValidator:
    """Maps a token to an identity; anything else is an invalid token."""

    def __init__(self, identities: dict[str, Identity]) -> None:
        self._identities = identities

    def validate(self, token: str) -> Identity:
        if token not in self._identities:
            raise AuthError("unknown token")
        return self._identities[token]


class FakeCampaigns:
    """The store calls the API makes, recorded instead of touching a database."""

    def __init__(self) -> None:
        self.approvals: dict[tuple[str, str], set[str]] = {}
        self.signals: list[tuple[str, str, str]] = []
        self.started: list[str] = []

    def grant(self, dsn: str, campaign_id: str, gate: str, approver: str, needed: int) -> Any:
        key = (campaign_id, gate)
        approvers = self.approvals.setdefault(key, set())
        approvers.add(approver)
        return len(approvers), len(approvers) >= needed

    def record(self, dsn: str, campaign_id: str) -> dict[str, Any]:
        return {"id": campaign_id, "status": "planned", "seal": None}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeCampaigns]:
    fake = FakeCampaigns()
    monkeypatch.setattr("argos_challenges.api.app.grant_approval", fake.grant)
    monkeypatch.setattr("argos_challenges.api.app.campaign_record", fake.record)

    async def start(campaign_id: str) -> str:
        fake.started.append(campaign_id)
        return f"campaign-{campaign_id}"

    async def signal(campaign_id: str, name: str, argument: str) -> None:
        fake.signals.append((campaign_id, name, argument))

    validator = FakeValidator(
        {
            "manager": MANAGER,
            "reviewer": REVIEWER,
            "reviewer2": SECOND_REVIEWER,
            "auditor": AUDITOR,
            "stranger": STRANGER,
        }
    )
    app = create_app("postgresql://unused", validator, start, signal)  # type: ignore[arg-type]
    return TestClient(app), fake


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_needs_no_token(client: tuple[TestClient, FakeCampaigns]) -> None:
    api, _ = client
    assert api.get("/health").json()["status"] == "ok"


def test_without_a_token_nothing_is_reachable(client: tuple[TestClient, FakeCampaigns]) -> None:
    api, _ = client
    assert api.get(f"/campaigns/{CAMPAIGN}").status_code == 401
    assert api.post("/campaigns", json={"name": "Campaña"}).status_code == 401
    assert api.get(f"/campaigns/{CAMPAIGN}", headers=_headers("nope")).status_code == 401


def test_a_realm_role_is_required(client: tuple[TestClient, FakeCampaigns]) -> None:
    api, _ = client
    assert api.get(f"/campaigns/{CAMPAIGN}", headers=_headers("stranger")).status_code == 403


@pytest.mark.parametrize(
    ("token", "expected"),
    [("manager", 200), ("reviewer", 403), ("auditor", 403)],
)
def test_only_the_manager_launches(
    client: tuple[TestClient, FakeCampaigns], token: str, expected: int
) -> None:
    api, fake = client
    response = api.post(f"/campaigns/{CAMPAIGN}/launch", headers=_headers(token))
    assert response.status_code == expected
    if expected == 200:
        assert fake.started == [CAMPAIGN]


@pytest.mark.parametrize(
    ("token", "expected"),
    [("reviewer", 200), ("manager", 403), ("auditor", 403)],
)
def test_only_the_reviewer_approves(
    client: tuple[TestClient, FakeCampaigns], token: str, expected: int
) -> None:
    api, _ = client
    response = api.post(f"/campaigns/{CAMPAIGN}/gates/start/approve", headers=_headers(token))
    assert response.status_code == expected


def test_a_simple_gate_opens_with_one_approval(client: tuple[TestClient, FakeCampaigns]) -> None:
    api, fake = client
    body = api.post(f"/campaigns/{CAMPAIGN}/gates/start/approve", headers=_headers("reviewer"))
    assert body.json() == {"gate": "start", "approvals": 1, "needed": 1, "state": "approved"}
    assert fake.signals == [(CAMPAIGN, "approve", "start")]


def test_the_sampling_gate_needs_two_different_people(
    client: tuple[TestClient, FakeCampaigns],
) -> None:
    api, fake = client
    assert "sampling" in DOUBLE_CONTROL_GATES
    first = api.post(f"/campaigns/{CAMPAIGN}/gates/sampling/approve", headers=_headers("reviewer"))
    assert first.json()["state"] == "awaiting_second_approval"
    assert fake.signals == []
    again = api.post(f"/campaigns/{CAMPAIGN}/gates/sampling/approve", headers=_headers("reviewer"))
    assert again.json()["approvals"] == 1  # the same person does not count twice
    second = api.post(
        f"/campaigns/{CAMPAIGN}/gates/sampling/approve", headers=_headers("reviewer2")
    )
    assert second.json() == {
        "gate": "sampling",
        "approvals": 2,
        "needed": 2,
        "state": "approved",
    }
    assert fake.signals == [(CAMPAIGN, "approve", "sampling")]


def test_the_launch_without_a_runner_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "argos_challenges.api.app.campaign_record",
        lambda dsn, campaign_id: {"id": campaign_id, "status": "planned", "seal": None},
    )
    validator = FakeValidator({"manager": MANAGER})
    api = TestClient(create_app("postgresql://unused", validator))  # type: ignore[arg-type]
    response = api.post(f"/campaigns/{CAMPAIGN}/launch", headers=_headers("manager"))
    assert response.status_code == 503


@pytest.mark.parametrize(
    "path",
    [
        "/campaigns/abc/verdicts",
        "/campaigns/abc/findings",
        "/campaigns/1;DROP/gates",
    ],
)
def test_an_id_that_is_not_a_uuid_never_reaches_the_database(
    client: tuple[TestClient, FakeCampaigns], path: str
) -> None:
    api, _ = client
    assert api.get(path, headers=_headers("auditor")).status_code == 422


def test_a_database_error_says_nothing_about_the_database(
    client: tuple[TestClient, FakeCampaigns],
) -> None:
    # The DSN of the fixture is unreachable: the answer must not describe it.
    api, _ = client
    response = api.get(f"/campaigns/{CAMPAIGN}/verdicts", headers=_headers("auditor"))
    assert response.status_code == 503
    assert response.json() == {"detail": "the campaign store is not available"}


def test_the_api_description_is_not_published_by_default(
    client: tuple[TestClient, FakeCampaigns],
) -> None:
    api, _ = client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert api.get(path).status_code == 404


def test_the_api_description_can_be_published_in_development() -> None:
    validator = FakeValidator({})
    api = TestClient(create_app("postgresql://unused", validator, publish_docs=True))  # type: ignore[arg-type]
    assert api.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/findings/{CAMPAIGN}/transition", {"to": "in_remediation", "note": "x" * 2_001}),
        ("/campaigns", {"name": "Campaña", "scope": {"k": "x" * 20_000}}),
    ],
)
def test_oversized_bodies_are_refused(
    client: tuple[TestClient, FakeCampaigns], path: str, body: dict[str, Any]
) -> None:
    api, _ = client
    token = "reviewer" if path.startswith("/findings") else "manager"
    assert api.post(path, json=body, headers=_headers(token)).status_code == 422
