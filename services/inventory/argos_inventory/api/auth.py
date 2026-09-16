"""Bearer authentication of the inventory API: any realm role may read (note ARG-029-030)."""

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from argos_auth import ROLES, AuthError, Identity, JwtValidator

_SCHEME = "bearer "
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def reader_dependency(validator: JwtValidator) -> Callable[[Request], Identity]:
    def require_reader(request: Request) -> Identity:
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
        return identity

    return require_reader
