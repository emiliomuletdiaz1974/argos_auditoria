"""K-04 · bootstrap of the bench: migrations, dynamic database credentials and JetStream streams.

What `make dev` did with tools/migrate.py, tools/dev_db_users.py (with
platform/vault/database-engine.sh) and tools/nats_streams.py, as one idempotent Job:

1. applies the migrations of ARGOS as the superuser, whose password the seeder generated;
2. gives `vault_admin` (migration 0035) a random password, hands it to the `database` engine of
   Vault in the body of a request and lets Vault rotate it at once: afterwards only Vault knows it.
   Each service gets its Vault role, which creates an ephemeral user inside the PostgreSQL role of
   that service (migration 0033), for 24 h and never more than 72 h;
3. creates or updates the JetStream streams with the user `platform`;
4. gives Keycloak its own role and database (K-05), with the password the seeder generated.

It signs in to Vault with its own service account (kubernetes auth, role `bootstrap`). It shows no
password and no token. Running it again changes nothing that matters: the admin password is simply
rotated once more.
"""

import asyncio
import json
import os
import secrets
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

PG_HOST = "postgres.argos-core.svc:5432"
DB_NAME = "argos"
NATS_URL = "tls://nats.argos-core.svc:4222"
TLS_DIR = Path("/tls")  # its certificate, key and the CA of the bench (certificate.yaml)
VAULT_ADDR = "http://vault.argos-core.svc:8200"
ACCOUNT_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
MIGRATIONS = Path("/app/services/api/migrations")
# K-07: the simulated sources of the bench, next to this script in its ConfigMap.
SYSTEMS = Path(__file__).with_name("systems.json")
# PostgreSQL is verified with the CA that signed its certificate: here, mounted by the Job; in
# Vault, mounted in its pod (Vault 1.17 ignores `tls_ca` in the configuration).
PG_TLS = "sslmode=verify-full&sslrootcert=/tls/ca.crt"
VAULT_PG_TLS = "sslmode=verify-full&sslrootcert=/run/postgres-ca/ca.crt"
DEFAULT_TTL = "24h"
MAX_TTL = "72h"
# Vault role -> PostgreSQL role of the service (platform/vault/database-engine.sh).
SERVICE_ROLES = {
    "api": "svc_api",
    "webhook": "svc_webhook",
    "challenge": "svc_challenge",
    "evidence": "svc_evidence",
    "ai-gateway": "svc_ai_gateway",
    "inventory": "svc_inventory",
    "ontology": "svc_ontology",
    "health": "svc_health",
}

Vault = Callable[[str, str, dict[str, Any] | None], Any]


class VaultRefusedError(RuntimeError):
    """Vault said no: what was asked and the reasons Vault gave, never the body that was sent."""

    def __init__(self, method: str, path: str, status: int, errors: list[str]) -> None:
        super().__init__(f"Vault refused {method} {path} ({status}): {'; '.join(errors)}")
        self.status = status


def _superuser_dsn() -> str:
    from urllib.parse import quote

    password = quote(os.environ["ARGOS_PG_PASSWORD"], safe="")
    return f"postgresql://argos:{password}@{PG_HOST}/{DB_NAME}?{PG_TLS}"


def migrate(dsn: str) -> list[int]:
    from argos_common.migrations import apply_migrations

    return apply_migrations(dsn, MIGRATIONS)


def vault_client() -> Vault:
    """A small client of the Vault API with a token of the role `bootstrap`."""

    def call(method: str, path: str, body: dict[str, Any] | None = None, token: str = "") -> Any:
        request = urllib.request.Request(  # noqa: S310 - a fixed address of the cluster
            f"{VAULT_ADDR}/v1/{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-Vault-Token": token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
                raw = answer.read()
        except urllib.error.HTTPError as refused:
            try:
                errors = [str(e) for e in json.loads(refused.read() or b"{}").get("errors", [])]
            except ValueError:
                errors = []
            raise VaultRefusedError(method, path, refused.code, errors) from None
        return json.loads(raw) if raw else {}

    jwt = ACCOUNT_TOKEN.read_text(encoding="utf-8").strip()
    login = call("POST", "auth/kubernetes/login", {"role": "bootstrap", "jwt": jwt})
    token = str(login["auth"]["client_token"])

    def vault(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        answer = call(method, path, body, token)
        return answer.get("data", answer) if isinstance(answer, dict) else answer

    return vault


def _engine_configured(vault: Vault) -> bool:
    try:
        config = vault("GET", f"db/config/{DB_NAME}", None)
    except VaultRefusedError as refused:
        if refused.status == 404:
            return False
        raise
    return bool(config.get("plugin_name"))


def database_engine(vault: Vault, set_admin_password: Callable[[str], None]) -> None:
    """The engine and its connection once; the roles of the services on every run.

    The bootstrap runs again with every tag. Setting a new password for vault_admin and rotating it
    each time left the services without credentials while it lasted, and they restarted (K-07);
    a connection already in place is left as it is. Writing the roles again changes nothing in use.
    """
    if "db/" not in vault("GET", "sys/mounts", None):
        vault("POST", "sys/mounts/db", {"type": "database"})
    if not _engine_configured(vault):
        _connect_engine(vault, set_admin_password)
    _write_roles(vault)


def _connect_engine(vault: Vault, set_admin_password: Callable[[str], None]) -> None:
    password = secrets.token_urlsafe(32)
    set_admin_password(password)
    vault(
        "POST",
        f"db/config/{DB_NAME}",
        {
            "plugin_name": "postgresql-database-plugin",
            "allowed_roles": "svc-*",
            "connection_url": (
                f"postgresql://{{{{username}}}}:{{{{password}}}}@{PG_HOST}/{DB_NAME}?{VAULT_PG_TLS}"
            ),
            "username": "vault_admin",
            "password": password,
            "password_authentication": "scram-sha-256",
        },
    )
    vault("POST", f"db/rotate-root/{DB_NAME}", {})


def _write_roles(vault: Vault) -> None:
    for service, role in SERVICE_ROLES.items():
        vault(
            "POST",
            f"db/roles/svc-{service}",
            {
                "db_name": DB_NAME,
                "default_ttl": DEFAULT_TTL,
                "max_ttl": MAX_TTL,
                "creation_statements": (
                    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' "
                    f"VALID UNTIL '{{{{expiration}}}}' IN ROLE {role};"
                ),
                "revocation_statements": (
                    f'REASSIGN OWNED BY "{{{{name}}}}" TO {role}; '
                    'DROP ROLE IF EXISTS "{{name}}";'
                ),
            },
        )


def load_systems(path: Path = SYSTEMS) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["systems"]
    return systems


def _credentials(credentials: dict[str, Any], env: Mapping[str, str]) -> dict[str, str]:
    """A literal value stays; {"env": NAME} is taken from the environment (secret bench-sources)."""
    return {
        key: env[value["env"]] if isinstance(value, dict) else str(value)
        for key, value in credentials.items()
    }


def register_sources(
    vault: Vault,
    systems: list[dict[str, Any]],
    env: Mapping[str, str],
    upsert: Callable[[list[dict[str, Any]]], None],
) -> int:
    """The rows of argos.systems and the secret of each connector, as register_dev_sources.py.

    The hash key of a source already registered is kept, so its sample digests stay comparable.
    No credential goes to the database or to the output: the row names the path in Vault.
    """
    rows = []
    for system in systems:
        path = f"argos/data/connectors/{system['id']}"
        credentials = _credentials(system["credentials"], env)
        try:
            kept = vault("GET", path, None).get("data", {})
        except VaultRefusedError as refused:
            if refused.status != 404:
                raise
            kept = {}
        hash_key = kept.get("hash_key") or secrets.token_hex(32)
        vault("POST", path, {"data": {**credentials, "hash_key": hash_key}})
        rows.append(
            {
                "id": system["id"],
                "name": system["name"],
                "kind": system["kind"],
                "connection": {
                    "secret": f"connectors/{system['id']}",
                    "connector": system["connector"],
                    "config": system.get("config", {}),
                },
            }
        )
    upsert(rows)
    return len(rows)


def _systems_upsert(dsn: str) -> Callable[[list[dict[str, Any]]], None]:
    def upsert(rows: list[dict[str, Any]]) -> None:
        import psycopg

        with psycopg.connect(dsn) as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO argos.systems (id, name, kind, environment, connection)
                    VALUES (%s, %s, %s, 'staging', %s::jsonb)
                    ON CONFLICT (id) DO UPDATE
                       SET name = EXCLUDED.name, kind = EXCLUDED.kind,
                           connection = EXCLUDED.connection, updated_at = now()
                    """,
                    (row["id"], row["name"], row["kind"], json.dumps(row["connection"])),
                )

    return upsert


CONTENT_KEY = "argos-content"


class VaultContentSigner:
    """Signs with the transit key argos-content of the Vault of the bench, which never leaves it."""

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    def sign(self, data: bytes) -> bytes:
        import base64

        answer = self._vault(
            "POST", f"transit/sign/{CONTENT_KEY}", {"input": base64.b64encode(data).decode()}
        )
        return base64.b64decode(str(answer["signature"]).split(":", 2)[2])

    def public_key(self) -> bytes:
        import base64

        keys = self._vault("GET", f"transit/keys/{CONTENT_KEY}", None)["keys"]
        newest = keys[str(max(int(version) for version in keys))]
        return base64.b64decode(str(newest["public_key"]))


def _in_force(dsn: str) -> tuple[str | None, bool]:
    """The version in force, and whether the library of this image is exactly that bundle.

    It compares the hashes without verify_on_disk, which leaves a security event when they differ:
    here a different library is the normal case after it changed, not an alarm.
    """
    import hashlib

    from argos_ontology.bundle import bundle_files, signed_files
    from argos_ontology.store import version_in_force
    from argos_ontology.vocabulary import LIBRARY_DIR

    try:
        version = version_in_force(dsn)
    except LookupError:
        return None, False
    _, signed = signed_files(dsn, version)
    on_disk = {n: hashlib.sha256(d).hexdigest() for n, d in bundle_files(LIBRARY_DIR).items()}
    return version, signed == on_disk


def _newest_loaded(dsn: str) -> str | None:
    import psycopg

    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT version FROM argos.ontology_bundles").fetchall()
    versions = [str(r[0]) for r in rows if str(r[0]).count(".") == 2]
    return max(versions, key=lambda v: tuple(int(p) for p in v.split("."))) if versions else None


def _publish(dsn: str, version: str, signer: VaultContentSigner) -> None:
    from datetime import UTC, datetime

    from argos_ontology.bundle import publish_library
    from argos_ontology.vocabulary import LIBRARY_DIR

    publish_library(dsn, LIBRARY_DIR, version, datetime.now(UTC).date(), signer)


def publish_content(dsn: str, vault: Vault) -> str:
    """K-99 · the library of this image as the signed content in force (SEC-011).

    The engine compiles no campaign without signed content, and the bench had none. If the content
    in force is already this library, nothing is done; else it is published as the next version,
    signed by the Vault of the bench and pinned to its own key, as selfcheck --publish-content does
    in development. An appliance loads instead the bundles that arrive signed, through the airlock.
    """
    version, same = _in_force(dsn)
    if version is not None and same:
        return f"content {version} in force, as on disk"
    newest = _newest_loaded(dsn)
    if newest is None:
        following = "1.0.0"
    else:
        major, minor, patch = (int(part) for part in newest.split("."))
        following = f"{major}.{minor}.{patch + 1}"
    _publish(dsn, following, VaultContentSigner(vault))
    return f"content {following} published"


def _admin_password_setter(dsn: str) -> Callable[[str], None]:
    def set_password(password: str) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("ALTER ROLE vault_admin LOGIN PASSWORD {}").format(sql.Literal(password))
            )

    return set_password


def keycloak_statements(password: str, *, database_exists: bool) -> list[Any]:
    """The role of Keycloak always follows its secret; its database is created only once."""
    from psycopg import sql

    statements = [
        sql.SQL(
            "DO $$ BEGIN CREATE ROLE keycloak LOGIN; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        ),
        sql.SQL("ALTER ROLE keycloak LOGIN PASSWORD {}").format(sql.Literal(password)),
    ]
    if not database_exists:
        statements.append(sql.SQL("CREATE DATABASE keycloak OWNER keycloak"))
    return statements


def keycloak_database_statements() -> list[Any]:
    """Inside the database of Keycloak. AGE is preloaded for the whole server, and in a database
    without `ag_catalog` its hook breaks the DDL of others: Keycloak's migrations failed with
    "schema ag_catalog does not exist" in the test of the bench. Keycloak never uses it."""
    from psycopg import sql

    return [sql.SQL("CREATE EXTENSION IF NOT EXISTS age")]


def keycloak_database(dsn: str, password: str) -> None:
    import psycopg

    # CREATE DATABASE cannot run inside a transaction.
    with psycopg.connect(dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = 'keycloak'").fetchone()
        for statement in keycloak_statements(password, database_exists=exists is not None):
            conn.execute(statement)
    inside = dsn.replace(f"/{DB_NAME}?", "/keycloak?", 1)
    with psycopg.connect(inside, autocommit=True) as conn:
        for statement in keycloak_database_statements():
            conn.execute(statement)


def streams(password: str) -> int:
    import nats

    from argos_events import STREAMS, ensure_streams

    async def run() -> None:
        context = ssl.create_default_context(cafile=str(TLS_DIR / "ca.crt"))
        context.load_cert_chain(TLS_DIR / "tls.crt", TLS_DIR / "tls.key")
        nc = await nats.connect(NATS_URL, user="platform", password=password, tls=context)
        try:
            await ensure_streams(nc.jetstream())
        finally:
            await nc.close()

    asyncio.run(run())
    return len(STREAMS)


def main() -> int:
    dsn = _superuser_dsn()
    applied = migrate(dsn)
    print(f"migrations: {len(applied)} applied, schema up to date")
    vault = vault_client()
    database_engine(vault, _admin_password_setter(dsn))
    print(f"dynamic credentials: {len(SERVICE_ROLES)} roles, ttl {DEFAULT_TTL}, at most {MAX_TTL}")
    count = streams(os.environ["ARGOS_NATS_PLATFORM_PASSWORD"])
    print(f"streams: {count} ready")
    keycloak_database(dsn, os.environ["ARGOS_KEYCLOAK_DB_PASSWORD"])
    print("keycloak: role and database ready")
    count = register_sources(vault, load_systems(), os.environ, _systems_upsert(dsn))
    print(f"sources: {count} systems registered with their credentials in Vault")
    print(publish_content(dsn, vault))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
