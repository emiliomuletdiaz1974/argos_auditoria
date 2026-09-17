"""Bearer authentication of the campaign API: each route asks for the role it needs (ARG-047)."""

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from argos_auth import ROLES, AuthError, Identity, JwtValidator

_SCHEME = "bearer "
_CHALLENGE = {"WWW-Authenticate": "Bearer"}
MANAGER_ROLE = "campaign_manager"
REVIEWER_ROLE = "dpo_reviewer"


def role_dependency(
    validator: JwtValidator, role: str | None = None
) -> Callable[[Request], Identity]:
    """A dependency that demands a valid token and, when given, one realm role."""
    if role is not None and role not in ROLES:
        raise ValueError(f"unknown realm role: {role!r}")

    def require(request: Request) -> Identity:
        header = request.headers.get("authorization", "")
        token = header[len(_SCHEME) :].strip() if header.lower().startswith(_SCHEME) else ""
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required", _CHALLENGE)
        try:
            identity = validator.validate(token)
        except AuthError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token", _CHALLENGE) from None
        if not identity.roles & frozenset(ROLES):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "an ARGOS realm role is required")
        if role is not None and role not in identity.roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"the role {role} is required")
        return identity

    return require
