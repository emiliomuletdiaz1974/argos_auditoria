"""Validation of JWTs issued by Keycloak, realm argos (ARG-008)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from argos_common.config import get_config

ROLES = ("platform_admin", "campaign_manager", "dpo_reviewer", "read_only_auditor")


class AuthError(Exception):
    """Token rejected or missing the required role."""


class KeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class Identity:
    sub: str
    name: str
    roles: frozenset[str]

    @property
    def actor(self) -> str:
        """Actor under which this person's actions enter the journal (P-19)."""
        return f"user:{self.sub}"


class JwtValidator:
    def __init__(self, issuer: str, audience: str, keys: KeyProvider | None = None) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = keys or PyJWKClient(f"{issuer}/protocol/openid-connect/certs", cache_keys=True)

    def validate(self, token: str, required_role: str | None = None) -> Identity:
        if required_role is not None and required_role not in ROLES:
            raise ValueError(f"unknown role: {required_role}")
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from None
        roles = frozenset(claims.get("realm_access", {}).get("roles", []))
        if required_role is not None and required_role not in roles:
            raise AuthError(f"role {required_role} is required")
        return Identity(str(claims["sub"]), str(claims.get("preferred_username", "")), roles)


@lru_cache(maxsize=1)
def _default_validator() -> JwtValidator:
    cfg = get_config()
    return JwtValidator(cfg.OIDC_ISSUER, cfg.OIDC_AUDIENCE)


def validate(token: str, required_role: str | None = None) -> Identity:
    return _default_validator().validate(token, required_role)
