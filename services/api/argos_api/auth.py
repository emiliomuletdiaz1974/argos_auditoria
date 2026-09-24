"""Every route of the v1 demands a token of the argos realm (ARG-072 turns it into permissions)."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from argos_api.security_events import security_event
from argos_auth import ROLES, AuthError, Identity, JwtValidator

_CHALLENGE = {"WWW-Authenticate": "Bearer"}
bearer = HTTPBearer(auto_error=False, description="access token issued by the appliance Keycloak")


def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    validator: JwtValidator | None = getattr(request.app.state, "validator", None)
    if credentials is None or not credentials.credentials:
        security_event(request, "auth.token_missing", "anonymous", "refused")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required", _CHALLENGE)
    if validator is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no token validator", _CHALLENGE)
    try:
        identity = validator.validate(credentials.credentials)
    except AuthError as refused:
        # The kind of failure (expired, bad signature...), never the token (F09-08).
        reason = str(refused).rpartition(": ")[2][:80]
        security_event(request, "auth.token_rejected", "anonymous", "refused", {"reason": reason})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token", _CHALLENGE) from None
    if not identity.roles & frozenset(ROLES):
        security_event(request, "auth.no_role", identity.actor, "refused")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "an ARGOS realm role is required")
    return identity


CurrentIdentity = Annotated[Identity, Depends(authenticate)]
