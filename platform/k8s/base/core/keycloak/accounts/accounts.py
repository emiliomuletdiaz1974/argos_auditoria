"""K-05 · gives the accounts of the bench a temporary password, once, and keeps them for the person.

The realm of the bench carries no credential (tools/bench_realm.py). The first time, this Job signs
in to Keycloak as its temporary admin, gives each account of the realm without a password a random
temporary one (Keycloak makes its owner change it at the first sign-in) and keeps them in the secret
`bench-accounts` of argos-core. The person reads them on the VM with
platform/k8s/bench/accounts.sh. If that secret exists, nothing is touched again; a password an
account already has is never replaced. No password reaches the logs.

K-08: Keycloak imports a realm only once, so a change of the realm of the bench (the origin of the
front end, for instance) would never arrive. On every run the redirects and the web origins of each
client are put back in line with the realm the Job mounts (`realm-bench.json`); nothing else of a
client is touched.
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
REALM_FILE = Path("/realm/realm-bench.json")
SYNCED = ("redirectUris", "webOrigins")
DEFAULT_ROLES = f"default-roles-{REALM}"


class Realm(Protocol):
    def users_of_realm(self) -> dict[str, str]: ...

    def has_password(self, user_id: str) -> bool: ...

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None: ...


class Accounts(Protocol):
    def users_of_realm(self) -> dict[str, str]: ...

    def has_password(self, user_id: str) -> bool: ...

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None: ...

    def create_user(self, representation: dict[str, Any]) -> str: ...

    def grant_roles(self, user_id: str, roles: list[str]) -> None: ...

    def drop_otp(self, user_id: str) -> None: ...

    def set_required_actions(self, user_id: str, actions: list[str]) -> None: ...

    def unlock(self, user_id: str) -> None: ...


def provision(realm: Realm, keep: Callable[[dict[str, str]], None]) -> int:
    """Temporary passwords for the accounts without one; the others are never touched.

    An account that has a password, temporary or its owner's, is left as it is, so this can run on
    every version: it only reaches the accounts that are new.
    """
    given: dict[str, str] = {}
    for name, user_id in sorted(realm.users_of_realm().items()):
        if realm.has_password(user_id):
            continue
        password = secrets.token_urlsafe(18)
        realm.reset_password(user_id, {"type": "password", "value": password, "temporary": True})
        given[name] = password
    if given:
        keep(given)
    return len(given)


def create_missing_users(realm: Accounts, wanted: list[dict[str, Any]]) -> list[str]:
    """The accounts of the realm file that Keycloak does not have yet.

    Keycloak imports a realm once, so an account added to the realm of the bench later never
    arrives by itself. It is created here with the same required actions; its roles are mapped
    with their own call, because creating a user ignores them.
    """
    present = realm.users_of_realm()
    created = []
    for user in wanted:
        name = str(user["username"])
        if name in present:
            continue
        roles = [str(role) for role in user.get("realmRoles", [])]
        user_id = realm.create_user({k: v for k, v in user.items() if k != "realmRoles"})
        if roles:
            realm.grant_roles(user_id, roles)
        created.append(name)
    return created


def ensure_default_roles(realm: Accounts) -> list[str]:
    """Every account with the default roles of the realm, which it lacks if it was imported.

    An account imported with explicit roles does not get them, and without them its token lacks the
    audience `account`: the account page of Keycloak answered 401 (checked against 26.0.8). Granting
    a role the account already has changes nothing, so it is granted to every account, every run.
    """
    accounts = realm.users_of_realm()
    for name in sorted(accounts):
        realm.grant_roles(accounts[name], [DEFAULT_ROLES])
    return sorted(accounts)


def reset_accounts(
    realm: Accounts,
    names: list[str],
    wanted: list[dict[str, Any]],
    keep: Callable[[dict[str, str]], None],
) -> list[str]:
    """Another temporary password for these accounts, and their second factor to be set up again.

    For a person who spent their temporary password, or lost their authenticator: usually after
    failed sign-ins, so the account is unlocked too. Only accounts of the realm file are accepted;
    nothing is touched if one is not.
    """
    present, known = realm.users_of_realm(), {str(u["username"]): u for u in wanted}
    unknown = [name for name in names if name not in known or name not in present]
    if unknown:
        raise ValueError(f"not accounts of the bench: {', '.join(unknown)}")
    given: dict[str, str] = {}
    for name in names:
        user_id = present[name]
        password = secrets.token_urlsafe(18)
        realm.drop_otp(user_id)
        realm.reset_password(user_id, {"type": "password", "value": password, "temporary": True})
        realm.set_required_actions(user_id, [str(a) for a in known[name]["requiredActions"]])
        realm.unlock(user_id)
        given[name] = password
    if given:
        keep(given)
    return list(given)


class Clients(Protocol):
    def client(self, client_id: str) -> dict[str, Any] | None: ...

    def update_client(self, internal_id: str, representation: dict[str, Any]) -> None: ...


def sync_clients(realm: Clients, wanted: list[dict[str, Any]]) -> list[str]:
    """The clients whose redirects or web origins differ from the realm of the bench, put back."""
    changed = []
    for client in wanted:
        current = realm.client(client["clientId"])
        if current is None:
            continue
        fields = {key: client.get(key, []) for key in SYNCED}
        if all(current.get(key, []) == value for key, value in fields.items()):
            continue
        realm.update_client(str(current["id"]), {**current, **fields})
        changed.append(str(client["clientId"]))
    return changed


def _call(
    method: str,
    url: str,
    *,
    token: str = "",
    body: Any = None,
    form: bool = False,
    kind: str = "application/json",
) -> Any:
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        kind = "application/x-www-form-urlencoded" if form else kind
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

    def client(self, client_id: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"clientId": client_id})
        found = _call("GET", f"{self._base}/clients?{query}", token=self._token)
        return dict(found[0]) if found else None

    def update_client(self, internal_id: str, representation: dict[str, Any]) -> None:
        _call("PUT", f"{self._base}/clients/{internal_id}", token=self._token, body=representation)

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None:
        _call(
            "PUT",
            f"{self._base}/users/{user_id}/reset-password",
            token=self._token,
            body=credential,
        )

    def create_user(self, representation: dict[str, Any]) -> str:
        _call("POST", f"{self._base}/users", token=self._token, body=representation)
        return self.users_of_realm()[str(representation["username"])]

    def grant_roles(self, user_id: str, roles: list[str]) -> None:
        mappings = [
            _call("GET", f"{self._base}/roles/{urllib.parse.quote(role)}", token=self._token)
            for role in roles
        ]
        _call(
            "POST",
            f"{self._base}/users/{user_id}/role-mappings/realm",
            token=self._token,
            body=mappings,
        )

    def drop_otp(self, user_id: str) -> None:
        credentials = _call("GET", f"{self._base}/users/{user_id}/credentials", token=self._token)
        for credential in credentials:
            if credential.get("type") == "otp":
                _call(
                    "DELETE",
                    f"{self._base}/users/{user_id}/credentials/{credential['id']}",
                    token=self._token,
                )

    def set_required_actions(self, user_id: str, actions: list[str]) -> None:
        # Only the field that changes: Keycloak shows a locked account as `enabled: false`, and
        # writing back the whole account disabled it for good (bench, 2026-10-08).
        _call(
            "PUT",
            f"{self._base}/users/{user_id}",
            token=self._token,
            body={"requiredActions": actions},
        )

    def unlock(self, user_id: str) -> None:
        _call(
            "DELETE",
            f"{self._base}/attack-detection/brute-force/users/{user_id}",
            token=self._token,
        )
        _call("PUT", f"{self._base}/users/{user_id}", token=self._token, body={"enabled": True})


def _kubernetes(method: str, path: str, body: Any = None, kind: str = "application/json") -> int:
    token = (ACCOUNT / "token").read_text(encoding="utf-8").strip()
    try:
        _call(method, f"{API}{path}", token=token, body=body, kind=kind)
    except urllib.error.HTTPError as refused:
        return int(refused.code)
    return 200


def main() -> int:
    path = f"/api/v1/namespaces/{NAMESPACE}/secrets"

    def keep(given: dict[str, str]) -> None:
        """Add to the secret what was given now; what is there already stays as it is."""
        data = {name: base64.b64encode(value.encode()).decode() for name, value in given.items()}
        if _kubernetes("GET", f"{path}/{KEPT_IN}") == 200:
            status = _kubernetes(
                "PATCH", f"{path}/{KEPT_IN}", {"data": data}, "application/merge-patch+json"
            )
        else:
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": KEPT_IN, "labels": {"argos/generated": "true"}},
                "type": "Opaque",
                "data": data,
            }
            status = _kubernetes("POST", path, secret)
        if status not in (200, 201):
            raise RuntimeError(f"the secret {KEPT_IN} was not written: {status}")

    realm = KeycloakRealm(os.environ["KEYCLOAK_ADMIN_PASSWORD"])
    document = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    synced = sync_clients(realm, document["clients"]) or "none"
    print(f"clients put back in line with the realm: {synced}")
    resets = [name for name in os.environ.get("RESET_USERS", "").split(",") if name]
    if resets:
        done = reset_accounts(realm, resets, document["users"], keep)
        print(f"{len(done)} accounts reset, their new temporary password kept in {KEPT_IN}")
        return 0
    print(f"accounts created: {create_missing_users(realm, document['users']) or 'none'}")
    print(f"accounts with the default roles of the realm: {len(ensure_default_roles(realm))}")
    print(f"{provision(realm, keep)} accounts with a temporary password, kept in {KEPT_IN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
