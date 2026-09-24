"""ARG-008 · real tokens from the development realm."""

import pytest

from argos_auth import AuthError, JwtValidator

from .keycloak import ISSUER, token

pytestmark = pytest.mark.integration


def _test_token() -> str:
    return token("dpo.test")  # with its TOTP code since F09-07


def test_real_token_with_dpo_role() -> None:
    identity = JwtValidator(ISSUER, "argos-api").validate(
        _test_token(), required_role="dpo_reviewer"
    )
    assert identity.name == "dpo.test"
    assert identity.actor.startswith("user:")


def test_real_token_without_admin_role() -> None:
    with pytest.raises(AuthError):
        JwtValidator(ISSUER, "argos-api").validate(_test_token(), required_role="platform_admin")
