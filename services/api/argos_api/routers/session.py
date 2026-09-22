"""The open routes of the v1: opening and refreshing the console session (ADR-0013, PKCE).

The access token lives in the memory of the console and nowhere else; the refresh token never
reaches the browser's JavaScript: it travels in a cookie that only the refresh path can read. That
is why these routes are open —there is no access token yet to show— and why they answer with the
access token alone. They are not domain mutations either, so they do not go through the audited
route class.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from argos_api import API_PREFIX
from argos_api.http import pending

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "argos_refresh"
COOKIE_PATH = f"{API_PREFIX}/auth/refresh"
DEFAULT_COOKIE_AGE = 8 * 60 * 60
_CHALLENGE = {"WWW-Authenticate": "Bearer"}

CodeExchanger = Callable[[str, str, str], Awaitable[dict[str, Any]]]


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
        answer.set_cookie(
            COOKIE,
            str(refresh),
            max_age=int(tokens.get("refresh_expires_in", DEFAULT_COOKIE_AGE)),
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
    tokens: dict[str, Any] = await refresher(token)
    return _with_cookie(tokens, fallback_refresh=token)
