"""The only open route of the v1: refreshing the console session (ADR-0013, PKCE).

The access token lives in the memory of the console and nowhere else; the refresh token never
reaches the browser's JavaScript: it travels in a cookie that only this path can read. That is why
this route is open —there is no access token yet to show— and why it answers with the access token
alone. It is not a domain mutation either, so it does not go through the audited route class.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from argos_api import API_PREFIX
from argos_api.http import pending

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "argos_refresh"
COOKIE_PATH = f"{API_PREFIX}/auth/refresh"
DEFAULT_COOKIE_AGE = 8 * 60 * 60


@router.post("/refresh", summary="Exchange the refresh cookie for an access token")
async def refresh(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "no session cookie", {"WWW-Authenticate": "Bearer"}
        )
    refresher = getattr(request.app.state, "refresher", None)
    if refresher is None:
        pending("the session refresh")

    tokens: dict[str, Any] = await refresher(token)
    answer = JSONResponse(
        {
            "access_token": tokens["access_token"],
            "token_type": "Bearer",
            "expires_in": tokens.get("expires_in"),
        }
    )
    answer.set_cookie(
        COOKIE,
        tokens.get("refresh_token", token),
        max_age=int(tokens.get("refresh_expires_in", DEFAULT_COOKIE_AGE)),
        path=COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return answer
