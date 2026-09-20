"""ARG-071 · what happens around every route: idempotency and the journal entry (P-19).

This is a route class and not a middleware on purpose. A middleware runs before the route resolves
its dependencies, so it does not know yet who is calling; here the identity the guard resolved is
already at hand, the entry carries the real actor, and a call refused for lack of permission leaves
no trace of something that never happened.

The order matters: a repeated `Idempotency-Key` answers with the stored response without touching
the endpoint, so neither the effect nor the journal entry happens twice.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from psycopg.types.json import Jsonb

from argos_auth import AuthError, Identity, JwtValidator

MUTATIONS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replay"
JOURNAL_ACTION = "api.mutation"
ANONYMOUS = "user:anonymous"
_SCHEME = "bearer "


def request_fingerprint(method: str, path: str, body: bytes) -> str:
    """Two requests are the same one when their method, route and body are the same."""
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


class IdempotencyStore:
    """What was already answered for a key, so a retry does not create a second time."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def recall(self, actor: str, key: str, fingerprint: str) -> StoredResponse | None:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT request_sha256, status_code, response FROM argos.api_idempotency"
                " WHERE actor = %s AND key = %s",
                (actor, key),
            ).fetchone()
        if row is None:
            return None
        stored_fingerprint, status_code, response = row
        if str(stored_fingerprint) != fingerprint:
            raise IdempotencyConflictError(key)
        return StoredResponse(int(status_code), json.dumps(response).encode())

    def remember(
        self, actor: str, key: str, method: str, path: str, fingerprint: str, answer: StoredResponse
    ) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO argos.api_idempotency"
                " (actor, key, method, path, request_sha256, status_code, response)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    actor,
                    key,
                    method,
                    path,
                    fingerprint,
                    answer.status_code,
                    Jsonb(json.loads(answer.body or b"null")),
                ),
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


class CoreRoute(APIRoute):
    """Every route of the v1: idempotent when asked, audited when it changes something."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        run = super().get_route_handler()
        route = self.path

        async def handler(request: Request) -> Response:
            store: IdempotencyStore | None = getattr(request.app.state, "idempotency", None)
            journal: Any = getattr(request.app.state, "journal", None)
            mutating = request.method in MUTATIONS
            key = request.headers.get(IDEMPOTENCY_HEADER) if mutating else None

            fingerprint = ""
            actor = ANONYMOUS
            if key and store is not None:
                identity = identity_of(request)
                actor = identity.actor if identity else ANONYMOUS
                fingerprint = request_fingerprint(request.method, route, await request.body())
                replay = await asyncio.to_thread(self._recall, store, actor, key, fingerprint)
                if replay is not None:
                    return Response(
                        content=replay.body,
                        status_code=replay.status_code,
                        media_type="application/json",
                        headers={REPLAY_HEADER: "true"},
                    )

            response = await run(request)

            if mutating and response.status_code < 300:
                identity = identity_of(request)
                actor = identity.actor if identity else ANONYMOUS
                if key and store is not None:
                    answer = StoredResponse(response.status_code, bytes(response.body))
                    await asyncio.to_thread(
                        store.remember, actor, key, request.method, route, fingerprint, answer
                    )
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
            return response

        return handler

    @staticmethod
    def _recall(
        store: IdempotencyStore, actor: str, key: str, fingerprint: str
    ) -> StoredResponse | None:
        try:
            return store.recall(actor, key, fingerprint)
        except IdempotencyConflictError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"the key {key} was already used for another request",
            ) from None
