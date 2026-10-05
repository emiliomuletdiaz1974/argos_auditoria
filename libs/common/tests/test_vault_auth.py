"""K-06 · how a service signs in to Vault, in the cluster and out of it.

In the cluster each service signs in with the token of its Kubernetes service account, which the
kubelet rotates: nobody hands it a Vault token. The token Vault answers expires, so the service
signs in again before it does. Out of the cluster nothing changes: an AppRole for the database and
a fixed token for the rest. No Vault here: the requests are recorded.
"""

from pathlib import Path
from typing import Any

import pytest

from argos_common import vault_auth
from argos_common.config import ArgosConfig
from argos_common.secret_stores import VaultSecretStore

DSN = "postgresql://postgres:5432/argos?service=argos"


class Vault:
    """Answers each login with a new token that lives `ttl` seconds, and records what it got."""

    def __init__(self, ttl: float = 3600.0) -> None:
        self.ttl = ttl
        self.logins: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, addr: str, path: str, token: str | None, body: Any = None) -> Any:
        self.logins.append((path, dict(body or {})))
        return {"auth": {"client_token": f"t-{len(self.logins)}", "lease_duration": self.ttl}}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> Vault:
    fake = Vault()
    monkeypatch.setattr(vault_auth, "vault_request", fake)
    return fake


def _config(**values: Any) -> ArgosConfig:
    return ArgosConfig(DATABASE_URL=DSN, **values)


def test_in_the_cluster_it_signs_in_with_the_current_token_of_its_account(
    vault: Vault, tmp_path: Path
) -> None:
    jwt = tmp_path / "token"
    jwt.write_text("jwt-1\n", encoding="utf-8")
    login = vault_auth.kubernetes_login("http://vault:8200", "svc-api", jwt)
    assert login() == ("t-1", 3600.0)
    jwt.write_text("jwt-2", encoding="utf-8")  # the kubelet rotated it
    login()
    assert vault.logins == [
        ("auth/kubernetes/login", {"role": "svc-api", "jwt": "jwt-1"}),
        ("auth/kubernetes/login", {"role": "svc-api", "jwt": "jwt-2"}),
    ]


def test_the_token_is_kept_and_renewed_before_it_expires() -> None:
    clock, answers = Clock(), iter([("t-1", 3600.0), ("t-2", 3600.0)])
    token = vault_auth.Renewing(lambda: next(answers), clock=clock)
    assert token() == "t-1"
    clock.now += 3600 - 61
    assert token() == "t-1", "one login serves until a minute before it expires"
    clock.now += 2
    assert token() == "t-2"


def test_a_short_token_is_renewed_at_half_its_life() -> None:
    clock, answers = Clock(), iter([("t-1", 60.0), ("t-2", 60.0)])
    token = vault_auth.Renewing(lambda: next(answers), clock=clock)
    token()
    clock.now += 31
    assert token() == "t-2"


def test_the_token_never_shows_in_its_repr() -> None:
    token = vault_auth.Renewing(lambda: ("s3cr3t-token", 3600.0))
    token()
    assert "s3cr3t-token" not in repr(token)


def test_a_service_of_the_cluster_reads_and_signs_with_its_account(
    vault: Vault, tmp_path: Path
) -> None:
    jwt = tmp_path / "token"
    jwt.write_text("jwt", encoding="utf-8")
    cfg = _config(VAULT_KUBERNETES_ROLE="svc-evidence", VAULT_KUBERNETES_TOKEN_FILE=str(jwt))
    assert vault_auth.service_token(cfg)() == "t-1"
    assert vault.logins[0][1]["role"] == "svc-evidence"


def test_out_of_the_cluster_the_fixed_token_is_kept(vault: Vault) -> None:
    assert vault_auth.service_token(_config(VAULT_TOKEN="dev-only-token"))() == "dev-only-token"
    assert vault_auth.service_token(_config())() == ""
    assert vault.logins == []


def test_the_database_credential_signs_in_with_the_account_before_the_approle(
    vault: Vault, tmp_path: Path
) -> None:
    jwt = tmp_path / "token"
    jwt.write_text("jwt", encoding="utf-8")
    approle = tmp_path / "approle"
    approle.mkdir()
    (approle / "role_id").write_text("r", encoding="utf-8")
    (approle / "secret_id").write_text("s", encoding="utf-8")
    both = _config(
        VAULT_KUBERNETES_ROLE="svc-api",
        VAULT_KUBERNETES_TOKEN_FILE=str(jwt),
        VAULT_APPROLE_DIR=str(approle),
    )
    login = vault_auth.database_login(both)
    assert login is not None
    login()
    assert vault.logins[-1][0] == "auth/kubernetes/login"
    login()
    # Vault revokes a lease when the token that asked for it expires: each credential is asked
    # for with a fresh token, never with one that may be about to expire.
    assert len(vault.logins) == 2
    only_approle = vault_auth.database_login(_config(VAULT_APPROLE_DIR=str(approle)))
    assert only_approle is not None
    only_approle()
    assert vault.logins[-1] == ("auth/approle/login", {"role_id": "r", "secret_id": "s"})
    assert vault_auth.database_login(_config()) is None


def test_the_secret_store_asks_for_the_current_token_on_every_call() -> None:
    tokens = iter(["t-1", "t-2"])
    store = VaultSecretStore("http://vault:8200", lambda: next(tokens))
    seen: list[str] = []

    def read_secret_version(**_: Any) -> Any:
        seen.append(store._client.token)
        return {"data": {"data": {"k": "v"}}}

    store._client.secrets.kv.v2.read_secret_version = read_secret_version  # type: ignore[method-assign,assignment]
    store.read("services/api/x")
    store.read("services/api/x")
    assert seen == ["t-1", "t-2"]
