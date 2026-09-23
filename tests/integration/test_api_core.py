"""ARG-071 · the core of the API against the real database: idempotency, journal and session.

The routes of the v1 still answer 501 —each arrives with its own task— so the effects that the core
has to guarantee are exercised over a probe route built with the same pieces, and every mutating
route of the application is walked to check that whatever answers correctly leaves its entry.
"""

import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import psycopg
import pytest
from fastapi import APIRouter, Depends, HTTPException
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import AUTHENTICATED, create_app
from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_auth import Identity, JwtValidator

pytestmark = pytest.mark.integration

BEARER = {"Authorization": "Bearer a-token"}
KEY = {"Idempotency-Key": "the-same-retry"}
MUTATING = ("POST", "PUT", "PATCH", "DELETE")


class RoleValidator:
    def __init__(self, role: str) -> None:
        self._role = role

    def validate(self, token: str) -> Identity:
        return Identity(sub=self._role, name=self._role, roles=frozenset({self._role}))


def _validator(role: str) -> JwtValidator:
    return cast(JwtValidator, RoleValidator(role))


@pytest.fixture
def journal_head(migrated_db: str) -> Iterator[int]:
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT coalesce(max(seq), 0) FROM argos.audit_journal").fetchone()
    yield int(row[0]) if row else 0


def _entries_since(dsn: str, seq: int) -> list[tuple[str, str, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT actor, action, payload_canon FROM argos.audit_journal WHERE seq > %s", (seq,)
        ).fetchall()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


def _probe_client(dsn: str, role: str = "campaign_manager") -> tuple[TestClient, list[int]]:
    """A route that behaves like a real one: it has an effect and answers 201."""
    calls: list[int] = []
    app = create_app(_validator(role), dsn=dsn)
    probe = APIRouter(route_class=CoreRoute)

    @probe.post("/probe", status_code=201, dependencies=[Depends(require_perm("campaigns.create"))])
    def run(body: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return {"runs": len(calls), "name": body.get("name")}

    app.include_router(probe, prefix=API_PREFIX)
    return TestClient(app), calls


def test_the_same_key_does_not_repeat_the_effect(migrated_db: str) -> None:
    client, calls = _probe_client(migrated_db)
    body = {"name": "the same request"}

    first = client.post(f"{API_PREFIX}/probe", json=body, headers={**BEARER, **KEY})
    second = client.post(f"{API_PREFIX}/probe", json=body, headers={**BEARER, **KEY})

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert len(calls) == 1, "the second call must not reach the endpoint"
    assert second.headers["Idempotent-Replay"] == "true"


def test_the_same_key_with_another_body_is_a_conflict(migrated_db: str) -> None:
    client, calls = _probe_client(migrated_db)
    client.post(f"{API_PREFIX}/probe", json={"name": "one"}, headers={**BEARER, **KEY})
    clash = client.post(f"{API_PREFIX}/probe", json={"name": "another"}, headers={**BEARER, **KEY})

    assert clash.status_code == 409
    assert clash.headers["content-type"].startswith("application/problem+json")
    assert len(calls) == 1


def test_without_a_key_every_call_is_a_new_one(migrated_db: str) -> None:
    client, calls = _probe_client(migrated_db)
    body = {"name": "no key"}
    client.post(f"{API_PREFIX}/probe", json=body, headers=BEARER)
    client.post(f"{API_PREFIX}/probe", json=body, headers=BEARER)
    assert len(calls) == 2


def test_a_mutation_that_works_leaves_its_entry(migrated_db: str, journal_head: int) -> None:
    client, _ = _probe_client(migrated_db)
    client.post(f"{API_PREFIX}/probe", json={"name": "audited"}, headers=BEARER)

    entries = [e for e in _entries_since(migrated_db, journal_head) if e[1] == "api.mutation"]
    assert len(entries) == 1
    actor, _, payload = entries[0]
    assert actor == "user:campaign_manager"
    assert '"method":"POST"' in payload.replace(" ", "")
    assert "/probe" in payload
    assert "201" in payload


def test_a_replay_does_not_write_a_second_entry(migrated_db: str, journal_head: int) -> None:
    client, _ = _probe_client(migrated_db)
    body = {"name": "once in the journal"}
    client.post(f"{API_PREFIX}/probe", json=body, headers={**BEARER, **KEY})
    client.post(f"{API_PREFIX}/probe", json=body, headers={**BEARER, **KEY})

    entries = [e for e in _entries_since(migrated_db, journal_head) if e[1] == "api.mutation"]
    assert len(entries) == 1


def test_a_refused_call_leaves_no_entry(migrated_db: str, journal_head: int) -> None:
    client, _ = _probe_client(migrated_db, role="read_only_auditor")
    assert (
        client.post(f"{API_PREFIX}/probe", json={"name": "no"}, headers=BEARER).status_code == 403
    )
    assert _entries_since(migrated_db, journal_head) == []


def test_every_mutating_route_that_answers_leaves_its_entry(
    migrated_db: str, journal_head: int
) -> None:
    """Today they all answer 501; as each task implements one, this test starts to bite."""
    client = TestClient(create_app(_validator("platform_admin"), dsn=migrated_db))
    answered = 0
    for router in AUTHENTICATED:
        for route in router.routes:
            for method in sorted(getattr(route, "methods", set())):
                if method not in MUTATING:
                    continue
                response = client.request(method, _fill(API_PREFIX + route.path), headers=BEARER)
                if response.status_code < 300:
                    answered += 1
    entries = [e for e in _entries_since(migrated_db, journal_head) if e[1] == "api.mutation"]
    assert len(entries) == answered


def _fill(path: str) -> str:
    return (
        path.replace("{campaign_id}", "00000000-0000-4000-8000-000000000001")
        .replace("{finding_id}", "00000000-0000-4000-8000-000000000002")
        .replace("{node_key}", "n-1")
        .replace("{credential_id}", "urn:uuid:0")
        .replace("{verdict_id}", "v-1")
        .replace("{webhook_id}", "w-1")
        .replace("{gate}", "sampling")
    )


def test_the_session_is_refreshed_from_the_cookie_and_never_from_a_header(migrated_db: str) -> None:
    async def refresher(token: str) -> dict[str, Any]:
        assert token == "the-refresh-token"
        return {"access_token": "a-fresh-one", "expires_in": 300, "refresh_token": "the-next-one"}

    app = create_app(_validator("dpo_reviewer"), dsn=migrated_db, refresher=refresher)
    client = TestClient(app)

    nothing = client.post(f"{API_PREFIX}/auth/refresh")
    assert nothing.status_code == 401
    assert nothing.headers["content-type"].startswith("application/problem+json")

    client.cookies.set("argos_refresh", "the-refresh-token")
    answer = client.post(f"{API_PREFIX}/auth/refresh")
    assert answer.status_code == 200
    assert answer.json()["access_token"] == "a-fresh-one"
    assert "refresh_token" not in answer.json()

    cookie = answer.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert f"Path={API_PREFIX}/auth" in cookie  # refresh and logout (F09-30)


# --- Security review F09-02: SEC-029, SEC-040, SEC-044 -------------------------------------------


class PersonValidator:
    """The same person, with the roles the test gives them at each moment."""

    def __init__(self, roles: set[str]) -> None:
        self.roles = roles

    def validate(self, token: str) -> Identity:
        return Identity(sub="the-person", name="the-person", roles=frozenset(self.roles))


def _keyed_client(dsn: str, validator: Any, delay: float = 0.0) -> tuple[TestClient, list[str]]:
    """A route with the campaign in its path, as the real ones have it."""
    calls: list[str] = []
    app = create_app(cast(JwtValidator, validator), dsn=dsn)
    probe = APIRouter(route_class=CoreRoute)

    @probe.post(
        "/probe/{campaign}",
        status_code=201,
        dependencies=[Depends(require_perm("campaigns.create"))],
    )
    def run(campaign: str) -> dict[str, Any]:
        calls.append(campaign)
        time.sleep(delay)
        return {"campaign": campaign}

    app.include_router(probe, prefix=API_PREFIX)
    return TestClient(app), calls


def _key() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def test_an_oversized_key_is_refused_before_anything_runs(
    migrated_db: str, journal_head: int
) -> None:
    client, calls = _probe_client(migrated_db)
    answer = client.post(
        f"{API_PREFIX}/probe", json={"name": "x"}, headers={**BEARER, "Idempotency-Key": "k" * 8192}
    )
    assert answer.status_code == 400
    assert calls == []
    assert _entries_since(migrated_db, journal_head) == []


@pytest.mark.parametrize("key", ["with space", "semi;colon", "dot.ted", ""])
def test_a_key_outside_its_alphabet_is_refused(migrated_db: str, key: str) -> None:
    client, calls = _probe_client(migrated_db)
    answer = client.post(
        f"{API_PREFIX}/probe", json={"name": "x"}, headers={**BEARER, "Idempotency-Key": key}
    )
    assert answer.status_code == 400
    assert calls == []


def test_a_key_reused_on_another_campaign_does_not_answer_with_the_first(
    migrated_db: str,
) -> None:
    client, calls = _keyed_client(migrated_db, PersonValidator({"campaign_manager"}))
    key = _key()
    first = client.post(f"{API_PREFIX}/probe/one", headers={**BEARER, **key})
    other = client.post(f"{API_PREFIX}/probe/two", headers={**BEARER, **key})
    assert first.status_code == 201
    assert other.status_code == 409, "another campaign is another request"
    assert "Idempotent-Replay" not in other.headers
    assert calls == ["one"]


def test_the_replay_comes_after_the_permission_guard(migrated_db: str) -> None:
    person = PersonValidator({"campaign_manager"})
    client, calls = _keyed_client(migrated_db, person)
    key = _key()
    assert client.post(f"{API_PREFIX}/probe/one", headers={**BEARER, **key}).status_code == 201

    person.roles = {"read_only_auditor"}  # the same person, who lost the permission
    again = client.post(f"{API_PREFIX}/probe/one", headers={**BEARER, **key})
    assert again.status_code == 403
    assert calls == ["one"]


def test_two_concurrent_calls_with_the_same_key_run_once(migrated_db: str) -> None:
    client, calls = _keyed_client(migrated_db, PersonValidator({"campaign_manager"}), delay=1.0)
    key = _key()
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(
            pool.map(
                lambda _: client.post(f"{API_PREFIX}/probe/one", headers={**BEARER, **key}),
                range(2),
            )
        )
    assert calls == ["one"]
    assert sorted(a.status_code for a in answers) == [201, 409]


def test_a_failed_call_frees_its_key(migrated_db: str) -> None:
    app = create_app(_validator("campaign_manager"), dsn=migrated_db)
    probe = APIRouter(route_class=CoreRoute)
    attempts: list[int] = []

    @probe.post("/flaky", status_code=201, dependencies=[Depends(require_perm("campaigns.create"))])
    def flaky() -> dict[str, Any]:
        attempts.append(1)
        if len(attempts) == 1:
            raise HTTPException(503, "try again")
        return {"ok": True}

    app.include_router(probe, prefix=API_PREFIX)
    client = TestClient(app)
    key = _key()
    assert client.post(f"{API_PREFIX}/flaky", headers={**BEARER, **key}).status_code == 503
    assert client.post(f"{API_PREFIX}/flaky", headers={**BEARER, **key}).status_code == 201
    assert len(attempts) == 2
