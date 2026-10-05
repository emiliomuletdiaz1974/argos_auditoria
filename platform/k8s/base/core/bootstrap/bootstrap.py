"""K-04 · bootstrap of the bench: migrations, dynamic database credentials and JetStream streams.

What `make dev` did with tools/migrate.py, tools/dev_db_users.py (with
platform/vault/database-engine.sh) and tools/nats_streams.py, as one idempotent Job:

1. applies the migrations of ARGOS as the superuser, whose password the seeder generated;
2. gives `vault_admin` (migration 0035) a random password, hands it to the `database` engine of
   Vault in the body of a request and lets Vault rotate it at once: afterwards only Vault knows it.
   Each service gets its Vault role, which creates an ephemeral user inside the PostgreSQL role of
   that service (migration 0033), for 24 h and never more than 72 h;
3. creates or updates the JetStream streams with the user `platform`.

It signs in to Vault with its own service account (kubernetes auth, role `bootstrap`). It shows no
password and no token. Running it again changes nothing that matters: the admin password is simply
rotated once more.
"""

import asyncio
import json
import os
import secrets
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PG_HOST = "postgres.argos-core.svc:5432"
DB_NAME = "argos"
NATS_URL = "nats://nats.argos-core.svc:4222"
VAULT_ADDR = "http://vault.argos-core.svc:8200"
ACCOUNT_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
MIGRATIONS = Path("/app/services/api/migrations")
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
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            raw = answer.read()
        return json.loads(raw) if raw else {}

    jwt = ACCOUNT_TOKEN.read_text(encoding="utf-8").strip()
    login = call("POST", "auth/kubernetes/login", {"role": "bootstrap", "jwt": jwt})
    token = str(login["auth"]["client_token"])

    def vault(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        answer = call(method, path, body, token)
        return answer.get("data", answer) if isinstance(answer, dict) else answer

    return vault


def database_engine(vault: Vault, set_admin_password: Callable[[str], None]) -> None:
    if "db/" not in vault("GET", "sys/mounts", None):
        vault("POST", "sys/mounts/db", {"type": "database"})
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


def _admin_password_setter(dsn: str) -> Callable[[str], None]:
    def set_password(password: str) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("ALTER ROLE vault_admin LOGIN PASSWORD {}").format(sql.Literal(password))
            )

    return set_password


def streams(password: str) -> int:
    import nats

    from argos_events import STREAMS, ensure_streams

    async def run() -> None:
        nc = await nats.connect(NATS_URL, user="platform", password=password)
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
    database_engine(vault_client(), _admin_password_setter(dsn))
    print(f"dynamic credentials: {len(SERVICE_ROLES)} roles, ttl {DEFAULT_TTL}, at most {MAX_TTL}")
    count = streams(os.environ["ARGOS_NATS_PLATFORM_PASSWORD"])
    print(f"streams: {count} ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
