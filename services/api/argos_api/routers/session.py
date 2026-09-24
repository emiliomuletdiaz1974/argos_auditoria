"""The open routes of the v1: opening, refreshing and closing the console session (ADR-0013, PKCE).

The access token lives in the memory of the console and nowhere else; the refresh token never
reaches the browser's JavaScript: it travels in a cookie that only the refresh and logout paths can
read. That is why these routes are open —there is no access token yet to show— and why they answer
with the access token alone. They are not domain mutations either, so they do not go through the
audited route class.
"""

import contextlib
import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from argos_api import API_PREFIX
from argos_api.http import pending
from argos_api.sessions import CLOSED_FOR, SessionClosures, sid_of

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "argos_refresh"
# The refresh and the logout read it; nothing else of the API sees it.
COOKIE_PATH = f"{API_PREFIX}/auth"
_CHALLENGE = {"WWW-Authenticate": "Bearer"}

CodeExchanger = Callable[[str, str, str], Awaitable[dict[str, Any]]]
SessionRevoker = Callable[[str], Awaitable[None]]


class Authorization(BaseModel):
    """What the console brings back from Keycloak: the code and the verifier it kept."""

    code: str = Field(min_length=1, max_length=4096)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9\-._~]{43,128}$")
    redirect_uri: str = Field(pattern="^https?://", max_length=2000)


def _with_cookie(tokens: dict[str, Any], fallback_refresh: str | None = None) -> JSONResponse:
    answer = JSONResponse(
        {
            "access_token": tokens["access_token"],
            "token_type": "Bearer",
            "expires_in": tokens.get("expires_in"),
        }
    )
    refresh = tokens.get("refresh_token", fallback_refresh)
    if refresh:
        # A session cookie: without `max_age` it dies with the browser, so a shared desk does not
        # keep the previous person signed in (security review F09-02, SEC-041). The realm still
        # bounds how long the refresh token itself is valid.
        answer.set_cookie(
            COOKIE,
            str(refresh),
            path=COOKIE_PATH,
            httponly=True,
            secure=True,
            samesite="strict",
        )
    return answer


@router.post("/session", summary="Open the console session from an authorization code (PKCE)")
async def open_session(request: Request, body: Authorization) -> JSONResponse:
    exchanger: CodeExchanger | None = getattr(request.app.state, "code_exchanger", None)
    if exchanger is None:
        pending("opening a session")
    try:
        tokens = await exchanger(body.code, body.code_verifier, body.redirect_uri)
    except PermissionError as refused:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"the sign-in was refused: {refused}", _CHALLENGE
        ) from None
    return _with_cookie(tokens)


@router.post("/refresh", summary="Exchange the refresh cookie for an access token")
async def refresh(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session cookie", _CHALLENGE)
    refresher = getattr(request.app.state, "refresher", None)
    if refresher is None:
        pending("the session refresh")
    try:
        tokens: dict[str, Any] = await refresher(token)
    except PermissionError as refused:
        # The realm said no (expired, revoked): the session is over, and the page signs in again.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"the session was refused: {refused}", _CHALLENGE
        ) from None
    return _with_cookie(tokens, fallback_refresh=token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Close the console session: revoke the refresh token and delete its cookie",
)
async def logout(request: Request) -> Response:
    token = request.cookies.get(COOKIE)
    revoker: SessionRevoker | None = getattr(request.app.state, "session_revoker", None)
    if token and revoker is not None:
        # Already expired or revoked at the realm: the cookie goes anyway.
        with contextlib.suppress(PermissionError):
            await revoker(token)
            # The realm accepted this very refresh token: its session is closed for the access
            # tokens too (F09-32, SEC-060). A cookie the realm refuses closes nothing.
            closures: SessionClosures | None = getattr(request.app.state, "closed_sessions", None)
            sid = sid_of(token)
            if closures is not None and sid:
                closures.close(sid, dt.datetime.now(dt.UTC) + CLOSED_FOR)
    answer = Response(status_code=status.HTTP_204_NO_CONTENT)
    answer.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, secure=True, samesite="strict")
    return answer
