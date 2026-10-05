"""K-04 · the bootstrap of the bench: migrations, dynamic credentials and streams, in that order.

It replaces what `make dev` did with three tools (migrate.py, dev_db_users.py, nats_streams.py).
The password of `vault_admin` is random, reaches Vault only in the body of a request, and Vault
rotates it at once: after the bootstrap, nobody but Vault knows it.
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
    / "bootstrap"
    / "bootstrap.py"
)


def _bootstrap() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Vault:
    def __init__(self, mounted: bool = False) -> None:
        self.mounted = mounted
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, path, body))
        if path == "sys/mounts":
            return {"db/": {}} if self.mounted else {}
        return {}

    def paths(self) -> list[str]:
        return [f"{method} {path}" for method, path, _ in self.calls]


def test_the_engine_gets_a_random_password_that_vault_rotates_at_once() -> None:
    bootstrap = _bootstrap()
    vault, admin = Vault(), []
    bootstrap.database_engine(vault, admin.append)
    [password] = admin
    assert len(password) >= 40
    paths = vault.paths()
    assert "POST sys/mounts/db" in paths
    config = paths.index("POST db/config/argos")
    assert paths.index("POST db/rotate-root/argos") > config, "rotated right after it is set"
    body = vault.calls[config][2]
    assert body is not None and body["password"] == password
    assert password not in body["connection_url"] and "{{password}}" in body["connection_url"]
    for _, path, _ in vault.calls:
        assert password not in path, "the password never travels in a path"


def test_an_engine_already_mounted_is_not_mounted_again() -> None:
    bootstrap = _bootstrap()
    vault = Vault(mounted=True)
    bootstrap.database_engine(vault, lambda password: None)
    assert "POST sys/mounts/db" not in vault.paths()


def test_each_service_gets_its_ephemeral_role_inside_its_own_postgres_role() -> None:
    bootstrap = _bootstrap()
    vault = Vault()
    bootstrap.database_engine(vault, lambda password: None)
    roles = {path: body for _, path, body in vault.calls if path.startswith("db/roles/")}
    for service, role in bootstrap.SERVICE_ROLES.items():
        body = roles[f"db/roles/svc-{service}"]
        assert body is not None
        assert f"IN ROLE {role};" in body["creation_statements"]
        assert body["default_ttl"] == "24h" and body["max_ttl"] == "72h"
    assert set(bootstrap.SERVICE_ROLES) >= {"api", "challenge", "evidence", "webhook", "health"}


def test_the_steps_run_in_order_and_no_secret_is_shown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bootstrap = _bootstrap()
    done: list[str] = []
    monkeypatch.setenv("ARGOS_PG_PASSWORD", "the-superuser-password")
    monkeypatch.setenv("ARGOS_NATS_PLATFORM_PASSWORD", "the-platform-password")
    monkeypatch.setattr(bootstrap, "migrate", lambda dsn: done.append("migrate") or [1, 2])
    monkeypatch.setattr(bootstrap, "vault_client", lambda: Vault())
    monkeypatch.setattr(
        bootstrap, "database_engine", lambda vault, set_password: done.append("engine")
    )
    monkeypatch.setattr(bootstrap, "streams", lambda password: done.append("streams") or 3)
    monkeypatch.setenv("ARGOS_KEYCLOAK_DB_PASSWORD", "the-keycloak-password")
    monkeypatch.setattr(
        bootstrap, "keycloak_database", lambda dsn, password: done.append("keycloak")
    )
    assert bootstrap.main() == 0
    assert done == ["migrate", "engine", "streams", "keycloak"]
    shown = capsys.readouterr().out
    assert "the-superuser-password" not in shown and "the-platform-password" not in shown
    assert "the-keycloak-password" not in shown


def test_a_refusal_of_vault_says_what_and_why_without_secrets() -> None:
    bootstrap = _bootstrap()
    error = bootstrap.VaultRefusedError(
        "POST", "db/config/argos", 400, ["error verifying connection"]
    )
    assert "POST db/config/argos" in str(error) and "error verifying connection" in str(error)


def test_keycloak_gets_its_role_and_database_once() -> None:
    bootstrap = _bootstrap()
    first = [
        q.as_string(None) for q in bootstrap.keycloak_statements("pw'1", database_exists=False)
    ]
    assert any(q.startswith("CREATE DATABASE keycloak OWNER keycloak") for q in first)
    assert any("PASSWORD 'pw''1'" in q for q in first), "the password is a literal, escaped"
    again = [q.as_string(None) for q in bootstrap.keycloak_statements("pw", database_exists=True)]
    assert not any("CREATE DATABASE" in q for q in again), "an existing database is kept"
    assert any(q.startswith("ALTER ROLE keycloak") for q in again), (
        "its password follows the secret"
    )


def test_the_database_of_keycloak_has_the_schema_age_expects() -> None:
    """AGE is preloaded for the whole server: in a database without `ag_catalog` its hook breaks
    the DDL of others (Keycloak's Liquibase failed on the bench test, K-05)."""
    bootstrap = _bootstrap()
    inside = [q.as_string(None) for q in bootstrap.keycloak_database_statements()]
    assert inside == ["CREATE EXTENSION IF NOT EXISTS age"]
