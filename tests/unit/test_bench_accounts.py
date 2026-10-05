"""K-05 · the accounts of the bench get a temporary password once, and only the person sees them.

The realm of the bench carries no credential. The first time, the Job gives each account without a
password a random temporary one, which Keycloak makes its owner change at the first sign-in, and
keeps them in the secret `bench-accounts` of the cluster: the person reads them on the VM, and
neither the repository nor the logs ever do. If that secret exists, nothing is touched again.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "platform"
    / "k8s"
    / "base"
    / "core"
    / "keycloak"
    / "accounts"
    / "accounts.py"
)


def _accounts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("accounts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Keycloak:
    def __init__(self, with_password: set[str]) -> None:
        self.users = {"dpo.test": "1", "manager.test": "2", "admin.test": "3", "auditor.test": "4"}
        self.with_password = with_password
        self.set: dict[str, dict[str, Any]] = {}

    def users_of_realm(self) -> dict[str, str]:
        return self.users

    def has_password(self, user_id: str) -> bool:
        return user_id in {self.users[name] for name in self.with_password}

    def reset_password(self, user_id: str, credential: dict[str, Any]) -> None:
        self.set[user_id] = credential


def test_each_account_without_password_gets_a_temporary_random_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    accounts = _accounts()
    keycloak, kept = Keycloak(with_password={"auditor.test"}), {}
    accounts.provision(keycloak, kept.update, secret_exists=False)
    assert set(kept) == {"dpo.test", "manager.test", "admin.test"}, "a password is never replaced"
    for name, password in kept.items():
        credential = keycloak.set[keycloak.users[name]]
        assert credential == {"type": "password", "value": password, "temporary": True}
        assert len(password) >= 20
        assert password not in capsys.readouterr().out, "no password in the logs"


def test_once_the_secret_exists_nothing_is_touched() -> None:
    accounts = _accounts()
    keycloak, kept = Keycloak(with_password=set()), {}
    accounts.provision(keycloak, kept.update, secret_exists=True)
    assert keycloak.set == {} and kept == {}


# ---------- K-08 · the clients follow the realm of the bench, without a manual step ----------


class Clients:
    def __init__(self, current: dict[str, dict[str, Any]]) -> None:
        self.current = current
        self.updated: dict[str, dict[str, Any]] = {}

    def client(self, client_id: str) -> dict[str, Any] | None:
        return self.current.get(client_id)

    def update_client(self, internal_id: str, representation: dict[str, Any]) -> None:
        self.updated[internal_id] = representation


def test_a_client_that_drifted_from_the_realm_of_the_bench_is_put_back() -> None:
    """An imported realm is not imported again: a changed redirect would never arrive."""
    accounts = _accounts()
    keycloak = Clients(
        {
            "argos-console": {
                "id": "c-1",
                "clientId": "argos-console",
                "redirectUris": ["http://127.0.0.1:5173/*"],
                "webOrigins": ["http://127.0.0.1:5173"],
                "publicClient": True,
            },
            "argos-api": {"id": "c-2", "clientId": "argos-api", "redirectUris": []},
        }
    )
    wanted = [
        {
            "clientId": "argos-console",
            "redirectUris": ["http://localhost:5173/*"],
            "webOrigins": ["http://localhost:5173"],
        },
        {"clientId": "argos-api", "redirectUris": []},
    ]
    assert accounts.sync_clients(keycloak, wanted) == ["argos-console"]
    updated = keycloak.updated["c-1"]
    assert updated["redirectUris"] == ["http://localhost:5173/*"]
    assert updated["webOrigins"] == ["http://localhost:5173"]
    assert updated["publicClient"] is True, "everything else of the client stays"
    assert "c-2" not in keycloak.updated, "a client already in line is not touched"
