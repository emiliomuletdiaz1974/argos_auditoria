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
    monkeypatch.setattr(bootstrap, "register_sources", lambda *args: done.append("sources") or 7)
    assert bootstrap.main() == 0
    assert done == ["migrate", "engine", "streams", "keycloak", "sources"]
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


# ---------- K-07 · the simulated sources, registered with the names of the cluster ----------


class KeptVault(Vault):
    """Answers the secret of a connector that already exists, with its hash key."""

    def __init__(self, kept: dict[str, dict[str, str]], refused: type[Exception]) -> None:
        super().__init__()
        self.kept = kept
        self.refused = refused

    def __call__(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("argos/data/connectors/"):
            system = path.rsplit("/", 1)[1]
            if system not in self.kept:
                raise self.refused(method, path, 404, [])
            return {"data": self.kept[system], "metadata": {}}
        return {}


ENV = {
    "ARGOS_SOURCE_SMB_PASSWORD": "smb-from-the-seeder",
    "ARGOS_SOURCE_S3_ACCESS": "s3-access-from-the-seeder",
    "ARGOS_SOURCE_S3_SECRET": "s3-secret-from-the-seeder",
    "ARGOS_SOURCE_LDAP_PASSWORD": "ldap-from-the-seeder",
}


def test_every_source_is_registered_with_the_credentials_of_the_cluster(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bootstrap = _bootstrap()
    systems = bootstrap.load_systems()
    vault, rows = KeptVault({}, bootstrap.VaultRefusedError), []
    assert bootstrap.register_sources(vault, systems, ENV, rows.extend) == len(systems)
    assert {r["id"] for r in rows} == {s["id"] for s in systems}
    assert all(".bench-sources.svc" in json_text(s["credentials"]) for s in systems)
    written = {p.rsplit("/", 1)[1]: b["data"] for m, p, b in vault.calls if m == "POST" and b}
    smb = written["01920000-0000-7000-8000-00000000b002"]
    assert smb["password"] == "smb-from-the-seeder"
    assert len(smb["hash_key"]) == 64
    for row in rows:
        assert row["connection"]["secret"] == f"connectors/{row['id']}", "the row names the path"
        assert "from-the-seeder" not in json_text(row), "no credential in the database"
    assert "from-the-seeder" not in capsys.readouterr().out


def test_the_hash_key_of_a_registered_source_is_kept() -> None:
    """Sample digests stay comparable between runs (tools/register_dev_sources.py)."""
    bootstrap = _bootstrap()
    [postgres] = [s for s in bootstrap.load_systems() if s["name"] == "bench-source-postgres"]
    vault = KeptVault({postgres["id"]: {"hash_key": "k" * 64}}, bootstrap.VaultRefusedError)
    bootstrap.register_sources(vault, [postgres], ENV, lambda rows: None)
    [(_, _, body)] = [c for c in vault.calls if c[0] == "POST"]
    assert body is not None and body["data"]["hash_key"] == "k" * 64


def test_a_credential_missing_from_the_environment_stops_the_registration() -> None:
    bootstrap = _bootstrap()
    with pytest.raises(KeyError):
        vault = KeptVault({}, bootstrap.VaultRefusedError)
        bootstrap.register_sources(vault, bootstrap.load_systems(), {}, lambda rows: None)


def test_the_catalog_of_the_bench_writes_no_secret() -> None:
    text = (SCRIPT.parent / "systems.json").read_text(encoding="utf-8")
    assert "dev-only" not in text and "127.0.0.1" not in text


def json_text(value: Any) -> str:
    import json

    return json.dumps(value)
