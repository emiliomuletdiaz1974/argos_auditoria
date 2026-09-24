"""ARG-008 · ARG-072 · the second factor of the people who decide, in the real realm (F09-07).

The DPO signs in with a TOTP code and the token says so (`amr` has `otp`); without the code there
is no token. The campaign manager signs in with the password alone (DP-14). In the browser, the
sign-in asks the DPO for the code after the password and does not ask the campaign manager. Five
wrong passwords lock the account for a while. The development TOTP secret lives in the development
realm and nowhere else in the repository.
"""

import base64
import hashlib
import html
import re
import secrets
import subprocess
import urllib.error
from pathlib import Path

import httpx
import pytest

from .keycloak import (
    ISSUER,
    PASSWORD,
    REALM_FILE,
    admin,
    claims,
    next_code,
    realm,
    sign_in,
    spent,
    token,
    totp_secret,
)

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
REDIRECT = "http://127.0.0.1:8000/callback"
LOCKOUT_USER = "lockout.test"


def _forget_failures(username: str) -> None:
    """A refused sign-in counts for the brute-force protection, and Keycloak also refuses the
    next attempt if it comes right after: other tests sign in as this user a moment later."""
    [user] = admin("GET", f"/users?username={username}&exact=true")
    admin("DELETE", f"/attack-detection/brute-force/users/{user['id']}")


def test_the_dpo_gets_no_token_without_the_second_factor() -> None:
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            sign_in("dpo.test")
        assert refused.value.code == 401
    finally:
        _forget_failures("dpo.test")


def test_with_the_totp_code_the_token_says_so() -> None:
    amr = claims(token("dpo.test")).get("amr")
    assert set(amr) == {"pwd", "otp"}


def test_the_campaign_manager_signs_in_with_the_password_alone() -> None:
    assert claims(token("manager.test")).get("amr") == ["pwd"]


def test_the_realm_asks_the_code_of_the_roles_that_decide() -> None:
    data = realm()
    assert data["otpPolicyAlgorithm"] == "HmacSHA256"
    assert data["otpPolicyDigits"] == 6
    assert data["otpPolicyPeriod"] == 30
    assert data["bruteForceProtected"] is True
    assert data["failureFactor"] == 5
    roles = {r["name"]: r for r in data["roles"]["realm"]}
    for role in ("platform_admin", "dpo_reviewer"):
        assert "mfa_required" in roles[role]["composites"]["realm"], role
    for role in ("campaign_manager", "read_only_auditor"):
        assert "composites" not in roles[role], role
    # What Keycloak runs, not only what the file says.
    live = {r["name"] for r in admin("GET", "/roles/dpo_reviewer/composites")}
    assert "mfa_required" in live


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def _form_action(page: str) -> str:
    match = re.search(r'<form[^>]*action="([^"]+)"', page)
    assert match, page[:500]
    return html.unescape(match.group(1))


class _Browser:
    """Keeps the cookies of the sign-in by hand: Keycloak marks them Secure and the test speaks
    plain HTTP to the development realm, where a real browser on localhost would still send them."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=10)
        self._cookies: dict[str, str] = {}

    def _send(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        cookie = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        response = self._http.request(method, url, headers={"Cookie": cookie}, **kwargs)  # type: ignore[arg-type]
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            self._cookies[name.strip()] = rest.split(";", 1)[0]
        return response

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self._send("POST", url, **kwargs)

    def close(self) -> None:
        self._http.close()


def _browser_sign_in(username: str) -> tuple[bool, dict[str, object]]:
    """Sign in as a browser would; whether the code was asked, and the token claims."""
    verifier, challenge = _pkce()
    browser = _Browser()
    try:
        page = browser.get(
            f"{ISSUER}/protocol/openid-connect/auth",
            params={
                "client_id": "argos-console",
                "redirect_uri": REDIRECT,
                "response_type": "code",
                "scope": "openid",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        answer = browser.post(
            _form_action(page.text), data={"username": username, "password": PASSWORD}
        )
        asked = 'name="otp"' in answer.text
        if asked:
            answer = browser.post(_form_action(answer.text), data={"otp": next_code(username)})
            if 'name="otp"' in answer.text:  # refused as used by another run: the next window
                spent(username)
                answer = browser.post(_form_action(answer.text), data={"otp": next_code(username)})
        assert answer.status_code == 302, answer.text[:500]
        code = httpx.URL(answer.headers["location"]).params["code"]
        issued = browser.post(
            f"{ISSUER}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "argos-console",
                "code": code,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            },
        )
        issued.raise_for_status()
    finally:
        browser.close()
    return asked, claims(str(issued.json()["access_token"]))


def test_in_the_browser_the_dpo_is_asked_for_the_code_after_the_password() -> None:
    asked, token_claims = _browser_sign_in("dpo.test")
    assert asked
    # `otp` is what the API asks for. After a code refused as spent Keycloak drops `pwd` from the
    # session it retries (seen with Keycloak 26.0), so only `otp` is required here.
    assert "otp" in token_claims["amr"]  # type: ignore[operator]


def test_in_the_browser_the_campaign_manager_is_not_asked_for_a_code() -> None:
    asked, token_claims = _browser_sign_in("manager.test")
    assert not asked
    assert token_claims["amr"] == ["pwd"]


def test_five_wrong_passwords_lock_the_account() -> None:
    [user] = admin("GET", f"/users?username={LOCKOUT_USER}&exact=true")
    try:
        for _ in range(5):
            with pytest.raises(urllib.error.HTTPError):
                sign_in(LOCKOUT_USER, password="wrong")  # noqa: S106
        with pytest.raises(urllib.error.HTTPError):
            sign_in(LOCKOUT_USER)  # the right password, and still refused
        assert admin("GET", f"/attack-detection/brute-force/users/{user['id']}")["disabled"]
    finally:
        _forget_failures(LOCKOUT_USER)


def test_the_development_totp_secret_lives_only_in_the_development_realm() -> None:
    secret = totp_secret("dpo.test")
    assert secret is not None and secret.startswith("dev-only-")
    # The files of the repository, versioned or about to be: ignored ones (dist/, .venv, the
    # regenerated map of the repository) are not published and may copy anything.
    listed = subprocess.run(  # noqa: S603 - fixed command
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    found = []
    for name in listed:
        path = REPO / name
        if not path.is_file() or path.suffix in {".png", ".pdf", ".pyc", ".gguf"}:
            continue
        if secret in path.read_text(encoding="utf-8", errors="ignore"):
            found.append(name)
    assert found == [REALM_FILE.relative_to(REPO).as_posix()]
