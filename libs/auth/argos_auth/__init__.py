"""Validation of JWTs issued by Keycloak, realm argos (ARG-008)."""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from argos_common.config import get_config

ROLES = ("platform_admin", "campaign_manager", "dpo_reviewer", "read_only_auditor")
# Authentication methods (RFC 8176) that count as a second factor. The realm reports `otp` when the
# person entered their TOTP code (F09-07).
SECOND_FACTORS = frozenset({"otp"})


class AuthError(Exception):
    """Token rejected or missing the required role."""


class KeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class Identity:
    sub: str
    name: str
    roles: frozenset[str]
    # How the person signed in, as the realm says in `amr` (F09-07): {"pwd"}, {"pwd", "otp"}...
    amr: frozenset[str] = field(default_factory=frozenset)
    # The session of the realm the token belongs to (`sid`), so a closed one is refused (F09-32).
    sid: str | None = None
    # The full name of the account (claim `name`), for what people read: a printed dossier.
    full_name: str = ""

    @property
    def actor(self) -> str:
        """Actor under which this person's actions enter the journal (P-19)."""
        return f"user:{self.sub}"

    @property
    def has_second_factor(self) -> bool:
        return bool(self.amr & SECOND_FACTORS)


LEEWAY_SECONDS = 30


def _realm_roles(realm_access: Any) -> frozenset[str]:
    """The roles of the realm, or none when the claim does not have the shape of Keycloak's: a
    list gave a 500 and a string a set of its characters (quality review QA-009)."""
    if not isinstance(realm_access, dict):
        return frozenset()
    roles = realm_access.get("roles")
    if not isinstance(roles, list):
        return frozenset()
    return frozenset(role for role in roles if isinstance(role, str))


class JwtValidator:
    def __init__(
        self,
        issuer: str,
        audience: str,
        keys: KeyProvider | None = None,
        *,
        realm_url: str | None = None,
    ) -> None:
        """`issuer` is what a token must carry; `realm_url`, where its keys are fetched when the
        issuer is a public address the service cannot reach from inside (K-08). By default, the
        issuer itself."""
        self._issuer = issuer
        self._audience = audience
        certs = f"{(realm_url or issuer).rstrip('/')}/protocol/openid-connect/certs"
        self._keys = keys or PyJWKClient(certs, cache_keys=True)

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
                # Two clocks never agree to the second (quality review QA-009).
                leeway=LEEWAY_SECONDS,
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from None
        roles = _realm_roles(claims.get("realm_access"))
        if required_role is not None and required_role not in roles:
            raise AuthError(f"role {required_role} is required")
        methods = claims.get("amr")
        amr = frozenset(str(m) for m in methods) if isinstance(methods, list) else frozenset()
        sid = str(claims["sid"]) if claims.get("sid") else None
        return Identity(
            str(claims["sub"]),
            str(claims.get("preferred_username", "")),
            roles,
            amr,
            sid,
            str(claims.get("name", "")),
        )


@lru_cache(maxsize=1)
def _default_validator() -> JwtValidator:
    cfg = get_config()
    return JwtValidator(cfg.OIDC_ISSUER, cfg.OIDC_AUDIENCE, realm_url=cfg.oidc_realm_url())


def validate(token: str, required_role: str | None = None) -> Identity:
    return _default_validator().validate(token, required_role)
