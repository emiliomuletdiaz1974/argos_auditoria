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


def test_the_full_name_of_the_person_comes_from_the_token(validator: JwtValidator) -> None:
    """What a printed dossier shows of whoever approved (claim `name` of the profile scope)."""
    assert validator.validate(_token(name="DPO Synthetic")).full_name == "DPO Synthetic"
    assert validator.validate(_token()).full_name == "", "an account without a name has none"


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
        {"exp": int(time.time()) - 120},  # beyond the leeway of 30 s
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


# --- F09-07: the second factor, as the realm reports it in `amr` (RFC 8176) -----------------------


def test_a_token_with_otp_carries_its_second_factor(validator: JwtValidator) -> None:
    identity = validator.validate(_token(amr=["pwd", "otp"]))
    assert identity.amr == frozenset({"pwd", "otp"})
    assert identity.has_second_factor


def test_a_token_with_the_password_alone_has_no_second_factor(validator: JwtValidator) -> None:
    assert not validator.validate(_token(amr=["pwd"])).has_second_factor
    assert not validator.validate(_token()).has_second_factor


def test_an_amr_that_is_not_a_list_is_not_a_second_factor(validator: JwtValidator) -> None:
    assert not validator.validate(_token(amr="otp")).has_second_factor


# Quality review QA-01 · QA-009


def test_a_token_issued_a_second_ahead_of_our_clock_is_accepted(validator: JwtValidator) -> None:
    """Two clocks never agree to the second: a small leeway, not a refusal."""
    now = int(time.time())
    identity = validator.validate(_token(iat=now + 1, exp=now + 300))
    assert identity.sub == "u-123"


def test_a_token_from_far_in_the_future_is_still_refused(validator: JwtValidator) -> None:
    now = int(time.time())
    with pytest.raises(AuthError):
        validator.validate(_token(iat=now + 3600, exp=now + 7200))


@pytest.mark.parametrize(
    "realm_access",
    [["dpo_reviewer"], "dpo_reviewer", {"roles": "dpo_reviewer"}, {"roles": [1, None]}],
)
def test_realm_roles_of_the_wrong_shape_give_no_role_and_no_500(
    validator: JwtValidator, realm_access: object
) -> None:
    identity = validator.validate(_token(realm_access=realm_access))
    assert identity.roles == frozenset()


def test_the_keys_come_from_inside_while_the_issuer_stays_the_public_one() -> None:
    """K-08: the bench publishes Keycloak at https://id.<host>; the API reaches it inside."""
    public = "https://id.34-134-21-66.sslip.io/realms/argos"
    inside = "http://keycloak.argos-core.svc:8080/realms/argos"
    validator = JwtValidator(public, "argos-api", realm_url=inside)
    assert validator._keys.uri == f"{inside}/protocol/openid-connect/certs"  # type: ignore[union-attr]
    assert validator._issuer == public


def test_without_an_inner_address_the_keys_come_from_the_issuer() -> None:
    validator = JwtValidator("http://127.0.0.1:8180/realms/argos", "argos-api")
    expected = "http://127.0.0.1:8180/realms/argos/protocol/openid-connect/certs"
    assert validator._keys.uri == expected  # type: ignore[union-attr]
