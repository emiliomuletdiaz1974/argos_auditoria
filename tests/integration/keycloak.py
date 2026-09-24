"""Tokens of the development realm for the tests, with the second factor when the user has it.

Since F09-07 the people who decide (`dpo_reviewer`, `platform_admin`) sign in with a TOTP code. The
secret of the development users is in the development realm (`deploy/dev/keycloak/realm-argos.json`)
and only there: the tests read it from that file, never from a copy.

Keycloak refuses a TOTP code that was already used, so a code serves one sign-in per 30 s window:
tokens are kept while they are valid and a new sign-in waits for the next window if it must.
"""

import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = os.environ.get("ARGOS_TEST_KEYCLOAK", "http://127.0.0.1:8180")
ISSUER = f"{BASE}/realms/argos"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
REALM_FILE = (
    Path(__file__).resolve().parents[2] / "deploy" / "dev" / "keycloak" / "realm-argos.json"
)
PASSWORD = "test"  # noqa: S105 - the development realm
PERIOD = 30

_tokens: dict[str, tuple[str, float]] = {}
_last_window: dict[str, int] = {}


def realm() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    return data


def totp_secret(username: str) -> str | None:
    """The development TOTP secret of a user, or None if the user has no second factor."""
    for user in realm()["users"]:
        if user["username"] == username:
            for credential in user.get("credentials", []):
                if credential["type"] == "otp":
                    return str(json.loads(credential["secretData"])["value"])
    return None


def totp(secret: str, at: float | None = None) -> str:
    """RFC 6238 with the policy of the realm: HMAC-SHA-256, 6 digits, 30 s."""
    counter = int((time.time() if at is None else at) // PERIOD)
    mac = hmac.new(secret.encode(), struct.pack(">Q", counter), hashlib.sha256).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _next_window() -> None:
    time.sleep(PERIOD - time.time() % PERIOD + 0.5)


def next_code(username: str) -> str:
    """A code of this user that this process has not used yet (Keycloak refuses a spent one)."""
    secret = totp_secret(username)
    if secret is None:
        raise ValueError(f"{username} has no second factor")
    if _last_window.get(username) == int(time.time() // PERIOD):
        _next_window()
    _last_window[username] = int(time.time() // PERIOD)
    return totp(secret)


def spent(username: str) -> None:
    """The code of this window was refused as used (another process took it): skip the window."""
    _last_window[username] = int(time.time() // PERIOD)


def sign_in(username: str, password: str = PASSWORD, code: str | None = None) -> dict[str, Any]:
    """One direct-grant sign-in; raises urllib.error.HTTPError when Keycloak refuses it."""
    form = {
        "grant_type": "password",
        "client_id": "argos-tests",
        "username": username,
        "password": password,
        "scope": "openid",
    }
    if code is not None:
        form["totp"] = code
    request = urllib.request.Request(  # noqa: S310 - the development realm
        TOKEN_URL, data=urllib.parse.urlencode(form).encode()
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        answer: dict[str, Any] = json.loads(response.read())
    return answer


def token(username: str) -> str:
    """A valid access token of the user, with the second factor when the user has one."""
    cached = _tokens.get(username)
    if cached and cached[1] > time.time():
        return cached[0]
    has_code = totp_secret(username) is not None
    retried = False
    for _ in range(30):  # Keycloak needs time to import the realm after starting
        try:
            answer = sign_in(username, code=next_code(username) if has_code else None)
            break
        except urllib.error.HTTPError as refused:
            if not has_code or retried or refused.code != 401:
                raise
            spent(username)  # the code may have been used by another run in this window
            retried = True
            time.sleep(1)  # Keycloak also refuses an attempt that comes right after a failure
        except OSError:
            time.sleep(2)
    else:
        raise RuntimeError("Keycloak did not issue a token")
    access = str(answer["access_token"])
    _tokens[username] = (access, time.time() + int(answer.get("expires_in", 60)) - 30)
    return access


def claims(access_token: str) -> dict[str, Any]:
    import base64

    part = access_token.split(".")[1]
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return decoded


def admin_token() -> str:
    form = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": "admin",
        "password": "admin",
    }
    request = urllib.request.Request(  # noqa: S310 - the development Keycloak
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data=urllib.parse.urlencode(form).encode(),
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return str(json.loads(response.read())["access_token"])


def admin(method: str, path: str) -> Any:
    request = urllib.request.Request(  # noqa: S310 - the development Keycloak
        f"{BASE}/admin/realms/argos{path}",
        method=method,
        headers={"Authorization": f"Bearer {admin_token()}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw) if raw else None
