"""K-05 · gives the accounts of the bench a temporary password, once, and keeps them for the person.

The realm of the bench carries no credential (tools/bench_realm.py). The first time, this Job signs
in to Keycloak as its temporary admin, gives each account of the realm without a password a random
temporary one (Keycloak makes its owner change it at the first sign-in) and keeps them in the secret
`bench-accounts` of argos-core. The person reads them on the VM with
platform/k8s/bench/accounts.sh. If that secret exists, nothing is touched again; a password an
account already has is never replaced. No password reaches the logs.
"""

import base64
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

KEYCLOAK = "http://keycloak.argos-core.svc:8080"
REALM = "argos"
ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
NAMESPACE = "argos-core"
KEPT_IN = "bench-accounts"


class Realm(Protocol):
    def users_of_realm(self) -> dict[str, str]: ...

    def has_password(self, user_id: str) -> bool: ...

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None: ...


def provision(realm: Realm, keep: Callable[[dict[str, str]], None], *, secret_exists: bool) -> int:
    """Temporary passwords for the accounts without one; nothing at all once they were kept."""
    if secret_exists:
        return 0
    given: dict[str, str] = {}
    for name, user_id in sorted(realm.users_of_realm().items()):
        if realm.has_password(user_id):
            continue
        password = secrets.token_urlsafe(18)
        realm.reset_password(user_id, {"type": "password", "value": password, "temporary": True})
        given[name] = password
    keep(given)
    return len(given)


def _call(method: str, url: str, *, token: str = "", body: Any = None, form: bool = False) -> Any:
    data, kind = None, "application/json"
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        kind = "application/x-www-form-urlencoded" if form else "application/json"
    headers = {"Content-Type": kind}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, method=method, data=data, headers=headers)  # noqa: S310
    context = None
    if url.startswith("https://"):
        context = ssl.create_default_context(cafile=str(ACCOUNT / "ca.crt"))
    with urllib.request.urlopen(request, context=context, timeout=30) as answer:  # noqa: S310
        raw = answer.read()
    return json.loads(raw) if raw else None


class KeycloakRealm:
    def __init__(self, admin_password: str) -> None:
        answer = _call(
            "POST",
            f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
            body={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "admin",
                "password": admin_password,
            },
            form=True,
        )
        self._token = str(answer["access_token"])
        self._base = f"{KEYCLOAK}/admin/realms/{REALM}"

    def users_of_realm(self) -> dict[str, str]:
        users = _call("GET", f"{self._base}/users?max=1000", token=self._token)
        return {str(u["username"]): str(u["id"]) for u in users}

    def has_password(self, user_id: str) -> bool:
        credentials = _call("GET", f"{self._base}/users/{user_id}/credentials", token=self._token)
        return any(c.get("type") == "password" for c in credentials)

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None:
        _call(
            "PUT",
            f"{self._base}/users/{user_id}/reset-password",
            token=self._token,
            body=credential,
        )


def _kubernetes(method: str, path: str, body: Any = None) -> int:
    token = (ACCOUNT / "token").read_text(encoding="utf-8").strip()
    try:
        _call(method, f"{API}{path}", token=token, body=body)
    except urllib.error.HTTPError as refused:
        return int(refused.code)
    return 200


def main() -> int:
    path = f"/api/v1/namespaces/{NAMESPACE}/secrets"
    exists = _kubernetes("GET", f"{path}/{KEPT_IN}") == 200

    def keep(given: dict[str, str]) -> None:
        data = {name: base64.b64encode(value.encode()).decode() for name, value in given.items()}
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": KEPT_IN, "labels": {"argos/generated": "true"}},
            "type": "Opaque",
            "data": data,
        }
        status = _kubernetes("POST", path, secret)
        if status not in (200, 201):
            raise RuntimeError(f"the secret {KEPT_IN} was not created: {status}")

    count = provision(
        KeycloakRealm(os.environ["KEYCLOAK_ADMIN_PASSWORD"]), keep, secret_exists=exists
    )
    print(
        f"{KEPT_IN} already there: nothing to do"
        if exists
        else f"{count} accounts with a temporary password, kept in {KEPT_IN}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
