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
    accounts.provision(keycloak, kept.update)
    assert set(kept) == {"dpo.test", "manager.test", "admin.test"}, "a password is never replaced"
    for name, password in kept.items():
        credential = keycloak.set[keycloak.users[name]]
        assert credential == {"type": "password", "value": password, "temporary": True}
        assert len(password) >= 20
        assert password not in capsys.readouterr().out, "no password in the logs"


def test_an_account_that_already_has_a_password_is_not_touched_even_with_the_secret_there() -> None:
    accounts = _accounts()
    keycloak, kept = (
        Keycloak(with_password={"dpo.test", "manager.test", "admin.test", "auditor.test"}),
        {},
    )
    assert accounts.provision(keycloak, kept.update) == 0
    assert keycloak.set == {} and kept == {}


# ---------- K-11 · a second DPO, created by the Job, and the reset of an account ----------


class Accounts(Keycloak):
    """The realm as the Job sees it, with what it needs to create and to reset an account."""

    def __init__(self, with_password: set[str]) -> None:
        super().__init__(with_password)
        self.created: list[dict[str, Any]] = []
        self.roles: dict[str, list[str]] = {}
        self.otp_dropped: list[str] = []
        self.actions: dict[str, list[str]] = {}

    def create_user(self, representation: dict[str, Any]) -> str:
        self.created.append(representation)
        user_id = str(10 + len(self.created))
        self.users[str(representation["username"])] = user_id
        return user_id

    def grant_roles(self, user_id: str, roles: list[str]) -> None:
        self.roles[user_id] = roles

    def drop_otp(self, user_id: str) -> None:
        self.otp_dropped.append(user_id)

    def set_required_actions(self, user_id: str, actions: list[str]) -> None:
        self.actions[user_id] = actions


WANTED = [
    {
        "username": "dpo.test",
        "enabled": True,
        "email": "dpo.test@argos.local",
        "realmRoles": ["dpo_reviewer"],
        "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
    },
    {
        "username": "dpo2.test",
        "enabled": True,
        "email": "dpo2.test@argos.local",
        "realmRoles": ["dpo_reviewer"],
        "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
    },
]


def test_the_accounts_of_the_realm_that_are_missing_in_keycloak_are_created_with_their_roles() -> (
    None
):
    """Keycloak imports a realm once: a new account of the bench would never arrive."""
    accounts = _accounts()
    keycloak = Accounts(with_password=set())
    assert accounts.create_missing_users(keycloak, WANTED) == ["dpo2.test"]
    [created] = keycloak.created
    assert created["username"] == "dpo2.test" and created["enabled"] is True
    assert created["requiredActions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    assert "realmRoles" not in created, "roles are mapped apart: the create call ignores them"
    assert keycloak.roles[keycloak.users["dpo2.test"]] == ["dpo_reviewer"]
    assert accounts.create_missing_users(keycloak, WANTED) == [], "once, not again"


def test_a_new_account_gets_its_temporary_password_with_the_secret_already_there() -> None:
    accounts = _accounts()
    keycloak, kept = (
        Accounts(with_password={"dpo.test", "manager.test", "admin.test", "auditor.test"}),
        {},
    )
    accounts.create_missing_users(keycloak, WANTED)
    assert accounts.provision(keycloak, kept.update) == 1
    assert set(kept) == {"dpo2.test"}, "the others keep the password their owner chose"


def test_resetting_an_account_drops_its_second_factor_and_asks_for_everything_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    accounts = _accounts()
    keycloak, kept = Accounts(with_password={"dpo.test"}), {}
    done = accounts.reset_accounts(keycloak, ["dpo.test"], WANTED, kept.update)
    assert done == ["dpo.test"]
    user_id = keycloak.users["dpo.test"]
    assert keycloak.otp_dropped == [user_id]
    assert keycloak.actions[user_id] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    credential = keycloak.set[user_id]
    assert credential["temporary"] is True and credential["value"] == kept["dpo.test"]
    assert len(kept["dpo.test"]) >= 20
    assert kept["dpo.test"] not in capsys.readouterr().out, "no password in the logs"


def test_only_the_accounts_of_the_realm_can_be_reset() -> None:
    accounts = _accounts()
    keycloak = Accounts(with_password=set())
    with pytest.raises(ValueError, match="nobody.test"):
        accounts.reset_accounts(keycloak, ["nobody.test"], WANTED, {}.update)
    assert keycloak.set == {} and keycloak.otp_dropped == []


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


def test_every_account_keeps_the_default_roles_of_the_realm() -> None:
    """An account imported with explicit roles has no default-roles-argos, and without them its
    token lacks the audience `account`: the account page of Keycloak answered 401 (the bench;
    against Keycloak 26.0.8, 401 without them and 200 with them). Granting it again changes nothing.
    """
    accounts = _accounts()
    keycloak = Accounts(with_password=set())
    assert accounts.ensure_default_roles(keycloak) == sorted(keycloak.users)
    assert all(roles == ["default-roles-argos"] for roles in keycloak.roles.values())
    assert set(keycloak.roles) == set(keycloak.users.values())
