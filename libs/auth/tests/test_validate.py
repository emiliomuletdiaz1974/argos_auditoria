"""JWT validation with local keys generated inside the test (ARG-008)."""

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from argos_auth import AuthError, JwtValidator

ISSUER = "http://127.0.0.1:8180/realms/argos"
AUDIENCE = "argos-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeys:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=KEY.public_key())


def _token(key: Any = KEY, alg: str = "RS256", **changes: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-123",
        "iat": now,
        "exp": now + 300,
        "preferred_username": "dpo.test",
        "realm_access": {"roles": ["dpo_reviewer"]},
    }
    claims.update(changes)
    for name in [k for k, v in claims.items() if v is None]:
        del claims[name]
    return jwt.encode(claims, key, algorithm=alg)


@pytest.fixture
def validator() -> JwtValidator:
    return JwtValidator(ISSUER, AUDIENCE, FakeKeys())


def test_valid_token_with_role(validator: JwtValidator) -> None:
    identity = validator.validate(_token(), required_role="dpo_reviewer")
    assert identity.sub == "u-123"
    assert identity.name == "dpo.test"
    assert identity.roles == frozenset({"dpo_reviewer"})
    assert identity.actor == "user:u-123"


def test_missing_role(validator: JwtValidator) -> None:
    with pytest.raises(AuthError, match="platform_admin"):
        validator.validate(_token(), required_role="platform_admin")


def test_unknown_role_is_a_programming_error(validator: JwtValidator) -> None:
    with pytest.raises(ValueError):
        validator.validate(_token(), required_role="superuser")


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "other-api"},
        {"iss": "http://attacker.example/realms/argos"},
        {"exp": int(time.time()) - 10},
        {"exp": None},
        {"sub": None},
    ],
    ids=["audience", "issuer", "expired", "no-exp", "no-sub"],
)
def test_invalid_claims(validator: JwtValidator, changes: dict[str, Any]) -> None:
    with pytest.raises(AuthError):
        validator.validate(_token(**changes))


def test_signed_with_another_key(validator: JwtValidator) -> None:
    with pytest.raises(AuthError):
        validator.validate(_token(key=OTHER_KEY))


def test_symmetric_algorithm_rejected(validator: JwtValidator) -> None:
    with pytest.raises(AuthError):
        validator.validate(_token(key="shared-secret-of-thirty-two-bytes", alg="HS256"))
