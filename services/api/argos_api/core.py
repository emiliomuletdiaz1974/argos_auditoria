"""ARG-071 · what happens around every route: idempotency and the journal entry (P-19).

This is a route class and not a middleware on purpose. A middleware runs before the route resolves
its dependencies, so it does not know yet who is calling; here the identity the guard resolved is
already at hand, the entry carries the real actor, and a call refused for lack of permission leaves
no trace of something that never happened.

The order matters (security review F09-02, SEC-029, SEC-040, SEC-044):

1. the permission guard of the route runs first, so a stored answer is never handed to somebody
   who may no longer make the request;
2. the `Idempotency-Key` is checked against its alphabet and reserved with an INSERT before the
   endpoint runs: of two equal requests at the same time, one runs and the other hears 409;
3. a repeated key answers with the stored response without touching the endpoint, so neither the
   effect nor the journal entry happens twice; the fingerprint covers the real path, so the same
   key on another campaign is another request;
4. the journal entry is written before the answer is stored, and a request that fails frees its
   key so it can be retried.
"""

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from psycopg.types.json import Jsonb

from argos_auth import AuthError, Identity, JwtValidator

MUTATIONS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replay"
JOURNAL_ACTION = "api.mutation"
ANONYMOUS = "user:anonymous"
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SCHEME = "bearer "


def request_fingerprint(method: str, path: str, body: bytes) -> str:
    """Two requests are the same one when their method, path and body are the same."""
    digest = hashlib.sha256()
    for part in (method.encode(), path.encode(), body):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: bytes


class IdempotencyConflictError(Exception):
    """The same key came back with a different request: the client changed its mind mid-retry."""


class IdempotencyInProgressError(Exception):
    """The same key is running right now in another request."""


class IdempotencyStore:
    """What was already answered for a key, so a retry does not create a second time."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def reserve(
        self, actor: str, key: str, method: str, path: str, fingerprint: str
    ) -> StoredResponse | None:
        """None when the key is ours now; the stored answer when it was already answered."""
        with psycopg.connect(self._dsn) as conn:
            taken = conn.execute(
                "INSERT INTO argos.api_idempotency (actor, key, method, path, request_sha256)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING 1",
                (actor, key, method, path, fingerprint),
            ).fetchone()
            if taken is not None:
                return None
            row = conn.execute(
                "SELECT request_sha256, status_code, response FROM argos.api_idempotency"
                " WHERE actor = %s AND key = %s",
                (actor, key),
            ).fetchone()
        if row is None:  # freed between the two statements: the other request failed
            raise IdempotencyInProgressError(key)
        stored_fingerprint, status_code, response = row
        if str(stored_fingerprint) != fingerprint:
            raise IdempotencyConflictError(key)
        if status_code is None:
            raise IdempotencyInProgressError(key)
        return StoredResponse(int(status_code), json.dumps(response).encode())

    def complete(self, actor: str, key: str, answer: StoredResponse) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE argos.api_idempotency SET status_code = %s, response = %s"
                " WHERE actor = %s AND key = %s",
                (answer.status_code, Jsonb(json.loads(answer.body or b"null")), actor, key),
            )

    def release(self, actor: str, key: str) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "DELETE FROM argos.api_idempotency"
                " WHERE actor = %s AND key = %s AND status_code IS NULL",
                (actor, key),
            )


def identity_of(request: Request) -> Identity | None:
    """Who is calling, as far as the token says; the route dependencies have the last word."""
    resolved = getattr(request.state, "identity", None)
    if isinstance(resolved, Identity):
        return resolved
    validator: JwtValidator | None = getattr(request.app.state, "validator", None)
    header = request.headers.get("authorization", "")
    if validator is None or not header.lower().startswith(_SCHEME):
        return None
    try:
        return validator.validate(header[len(_SCHEME) :].strip())
    except AuthError:
        return None


@dataclass(frozen=True, slots=True)
class _Reservation:
    actor: str
    key: str


class _Replay(Exception):  # noqa: N818 - control flow that carries the stored answer, not an error
    def __init__(self, answer: StoredResponse) -> None:
        super().__init__()
        self.answer = answer


async def idempotency_gate(request: Request) -> None:
    """The last dependency of every route: after the permission guard, before the endpoint."""
    store: IdempotencyStore | None = getattr(request.app.state, "idempotency", None)
    key = request.headers.get(IDEMPOTENCY_HEADER) if request.method in MUTATIONS else None
    if key is None or store is None or getattr(request.state, "reservation", None) is not None:
        return
    if not KEY_PATTERN.match(key):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{IDEMPOTENCY_HEADER} must be 1 to 128 letters, digits, '-' or '_'",
        )
    identity = await asyncio.to_thread(identity_of, request)
    actor = identity.actor if identity else ANONYMOUS
    path = request.url.path
    fingerprint = request_fingerprint(request.method, path, await request.body())
    try:
        replay = await asyncio.to_thread(
            store.reserve, actor, key, request.method, path, fingerprint
        )
    except IdempotencyConflictError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"the key {key} was already used for another request"
        ) from None
    except IdempotencyInProgressError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"the request with key {key} is still running"
        ) from None
    if replay is not None:
        raise _Replay(replay)
    request.state.reservation = _Reservation(actor, key)


class CoreRoute(APIRoute):
    """Every route of the v1: idempotent when asked, audited when it changes something."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        # Last, whatever the router adds: the gate needs the identity the guard resolved.
        declared = [
            d
            for d in kwargs.pop("dependencies", None) or []
            if d.dependency is not idempotency_gate
        ]
        super().__init__(
            path, endpoint, dependencies=[*declared, Depends(idempotency_gate)], **kwargs
        )

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        run = super().get_route_handler()
        route = self.path

        async def handler(request: Request) -> Response:
            store: IdempotencyStore | None = getattr(request.app.state, "idempotency", None)
            journal: Any = getattr(request.app.state, "journal", None)
            try:
                response = await run(request)
            except _Replay as replay:
                return Response(
                    content=replay.answer.body,
                    status_code=replay.answer.status_code,
                    media_type="application/json",
                    headers={REPLAY_HEADER: "true"},
                )
            except BaseException:
                await _release(request, store)
                raise

            if request.method not in MUTATIONS or response.status_code >= 300:
                await _release(request, store)
                return response
            identity = await asyncio.to_thread(identity_of, request)
            actor = identity.actor if identity else ANONYMOUS
            if journal is not None:
                await asyncio.to_thread(
                    journal.append,
                    actor,
                    JOURNAL_ACTION,
                    {
                        "method": request.method,
                        "route": route,
                        "path": request.url.path,
                        "status": response.status_code,
                    },
                )
            reservation: _Reservation | None = getattr(request.state, "reservation", None)
            if reservation is not None and store is not None:
                answer = StoredResponse(response.status_code, bytes(response.body))
                await asyncio.to_thread(store.complete, reservation.actor, reservation.key, answer)
            return response

        return handler


async def _release(request: Request, store: IdempotencyStore | None) -> None:
    reservation: _Reservation | None = getattr(request.state, "reservation", None)
    if reservation is not None and store is not None:
        await asyncio.to_thread(store.release, reservation.actor, reservation.key)
