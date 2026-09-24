"""F09-32 (SEC-060) · a token of a closed session is refused, even before it expires.

The API validates the JWT without state, and closing the session revoked only the refresh token:
its access token kept working until it expired (five minutes at most). Now the logout records the
session (`sid`) as closed, only if the realm accepted the revocation, and every token of that
session is refused from then on.
"""

import base64
import datetime as dt
import json
from typing import Any, cast

from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.sessions import ClosedSessions, sid_of
from argos_auth import Identity, JwtValidator


def _refresh(sid: str) -> str:
    """A refresh token as the realm writes it: only its `sid` matters to the API."""
    body = base64.urlsafe_b64encode(json.dumps({"sid": sid, "typ": "Refresh"}).encode())
    return "eyJhbGciOiJIUzI1NiJ9." + body.rstrip(b"=").decode() + ".signature"


class Tokens:
    """`Bearer <sid>`: a manager whose token belongs to that session."""

    def validate(self, token: str) -> Identity:
        return Identity(
            sub="manager", name="manager", roles=frozenset({"campaign_manager"}),
            amr=frozenset({"pwd"}), sid=token,
        )  # fmt: skip


class Memory:
    """The shared store of closed sessions, in memory."""

    def __init__(self) -> None:
        self.closed: dict[str, dt.datetime] = {}

    def close(self, sid: str, until: dt.datetime) -> None:
        self.closed[sid] = until

    def is_closed(self, sid: str) -> bool:
        until = self.closed.get(sid)
        return until is not None and until > dt.datetime.now(dt.UTC)


def _client(store: Any, revoked: list[str], accept: bool = True) -> TestClient:
    async def revoke(token: str) -> None:
        if not accept:
            raise PermissionError("invalid_grant")
        revoked.append(token)

    app = create_app(cast(JwtValidator, Tokens()), session_revoker=revoke, closed_sessions=store)
    return TestClient(app)


def _logout(client: TestClient, sid: str) -> int:
    client.cookies.set("argos_refresh", _refresh(sid), path=f"{API_PREFIX}/auth")
    return int(client.post(f"{API_PREFIX}/auth/logout").status_code)


def test_after_logout_the_token_of_that_session_is_refused() -> None:
    store, revoked = Memory(), list[str]()
    client = _client(store, revoked)
    assert (
        client.get(f"{API_PREFIX}/nothing", headers={"Authorization": "Bearer s-1"}).status_code
        == 404
    )
    assert _logout(client, "s-1") == 204
    answer = client.get(f"{API_PREFIX}/campaigns", headers={"Authorization": "Bearer s-1"})
    assert answer.status_code == 401
    assert "closed" in answer.text


def test_the_tokens_of_other_sessions_go_on() -> None:
    store = Memory()
    client = _client(store, [])
    _logout(client, "s-1")
    answer = client.get(f"{API_PREFIX}/nothing-here", headers={"Authorization": "Bearer s-2"})
    assert answer.status_code == 404


def test_a_cookie_the_realm_refuses_closes_nothing() -> None:
    store = Memory()
    client = _client(store, [], accept=False)
    assert _logout(client, "s-of-someone-else") == 204, "the cookie goes anyway"
    assert store.closed == {}, "a forged cookie cannot close the session of another person"


def test_the_closure_outlives_every_token_of_the_session() -> None:
    store = Memory()
    _logout(_client(store, []), "s-1")
    until = store.closed["s-1"]
    assert until - dt.datetime.now(dt.UTC) >= dt.timedelta(minutes=10)


def test_the_sid_is_read_from_the_refresh_token_without_trusting_it() -> None:
    assert sid_of(_refresh("abc")) == "abc"
    assert sid_of("not a token") is None
    assert sid_of("a.b.c") is None


def test_the_store_answers_from_a_short_cache() -> None:
    calls: list[str] = []

    class Counting(ClosedSessions):
        def _lookup(self, sid: str) -> bool:
            calls.append(sid)
            return sid == "closed"

    store = Counting("postgresql://unused", cache_seconds=60)
    assert store.is_closed("closed") and store.is_closed("closed")
    assert not store.is_closed("open")
    assert calls == ["closed", "open"], "each session is looked up once while the cache holds"
