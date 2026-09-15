"""ARG-008 · real tokens from the development realm."""

import json
import os
import time
import urllib.parse
import urllib.request

import pytest

from argos_auth import AuthError, JwtValidator

pytestmark = pytest.mark.integration
BASE = os.environ.get("ARGOS_TEST_KEYCLOAK", "http://127.0.0.1:8180")
ISSUER = f"{BASE}/realms/argos"


def _test_token() -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "argos-tests",
            "username": "dpo.test",
            "password": "test",
            "scope": "openid",
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310
        f"{ISSUER}/protocol/openid-connect/token", data=body
    )
    for _ in range(30):  # Keycloak needs time to import the realm after starting
        try:
            with urllib.request.urlopen(request, timeout=5) as r:  # noqa: S310
                return str(json.loads(r.read())["access_token"])
        except OSError:
            time.sleep(2)
    raise RuntimeError("Keycloak did not issue a token")


def test_real_token_with_dpo_role() -> None:
    identity = JwtValidator(ISSUER, "argos-api").validate(
        _test_token(), required_role="dpo_reviewer"
    )
    assert identity.name == "dpo.test"
    assert identity.actor.startswith("user:")


def test_real_token_without_admin_role() -> None:
    with pytest.raises(AuthError):
        JwtValidator(ISSUER, "argos-api").validate(_test_token(), required_role="platform_admin")
