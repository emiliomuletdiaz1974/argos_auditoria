"""Dynamic database credentials in the development environment (F09-04, F09-05).

No service has a database password of its own any more. After the migrations, `apply`:

1. gives `vault_admin` (migration 0035) a random password and hands it to Vault, which configures
   its `database` engine with `platform/vault/database-engine.sh` and rotates it right away: only
   Vault knows it afterwards;
2. drops the fixed login users of F09-04 (`login_<service>`), if they are still there;
3. creates one AppRole per service container, allowed to read only its own database credentials,
   and writes its `role_id` and `secret_id` to `deploy/dev/secrets/approle-<service>/` (gitignored),
   mounted read-only in the container. Nothing goes in an environment variable, so nothing shows in
   `docker inspect`.

Each service then asks Vault for an ephemeral user at start and before it expires
(`argos_common.dynamic_db`). It runs again on every `make dev`: Vault in development keeps its
state in memory and forgets it when it restarts.
"""

import json
import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from argos_common.config import get_config

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "deploy" / "dev" / "secrets"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy" / "dev" / "compose.yaml")]
ENGINE = ROOT / "platform" / "vault" / "database-engine.sh"
VAULT = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
TOKEN = os.environ.get("VAULT_TOKEN", "root")  # development Vault: -dev-root-token-id=root
# The service containers that reach the database, and the Vault role each one reads.
SERVICES = {
    "api": "svc-api",
    "webhook": "svc-webhook",
    "challenge": "svc-challenge",
    "evidence": "svc-evidence",
    "ai-gateway": "svc-ai-gateway",
    "example": "svc-example",
}
F0904_USERS = ("api", "webhook", "challenge", "evidence", "ai_gateway", "example")
# The AppRole token lives as long as the longest credential it reads: Vault revokes a lease
# when the token that asked for it expires.
TOKEN_TTL = "72h"  # noqa: S105 - a duration, not a password


def _vault(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - fixed development address
        f"{VAULT}/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-Vault-Token": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw) if raw else {}


def _admin_password() -> str:
    password = secrets.token_urlsafe(32)
    with psycopg.connect(get_config().DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE vault_admin LOGIN PASSWORD {}").format(sql.Literal(password))
        )
        for service in F0904_USERS:
            conn.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(f"login_{service}"))
            )
    return password


def _engine(admin_password: str) -> None:
    env = {**os.environ, "VAULT_DB_ADMIN_PW": admin_password}
    with ENGINE.open("rb") as script:
        subprocess.run(  # noqa: S603 - fixed command against the development environment
            [
                *COMPOSE,
                "exec",
                "-T",
                "-e",
                "VAULT_ADDR=http://127.0.0.1:8200",
                "-e",
                f"VAULT_TOKEN={TOKEN}",
                "-e",
                "VAULT_DB_ADMIN_PW",  # taken from the environment, never on the command line
                "vault",
                "sh",
                "-s",
            ],
            stdin=script,
            env=env,
            check=True,
        )


def _approles() -> None:
    methods = _vault("GET", "sys/auth")
    if "approle/" not in methods.get("data", methods):
        _vault("POST", "sys/auth/approle", {"type": "approle"})
    for service, role in SERVICES.items():
        policy = f'path "db/creds/{role}" {{\n  capabilities = ["read"]\n}}\n'
        _vault("PUT", f"sys/policies/acl/argos-db-{service}", {"policy": policy})
        _vault(
            "POST",
            f"auth/approle/role/argos-{service}",
            {
                "token_policies": [f"argos-db-{service}"],
                "token_ttl": TOKEN_TTL,
                "token_max_ttl": TOKEN_TTL,
                "token_no_default_policy": True,
            },
        )
        role_id = _vault("GET", f"auth/approle/role/argos-{service}/role-id")["data"]["role_id"]
        secret_id = _vault("POST", f"auth/approle/role/argos-{service}/secret-id", {})["data"][
            "secret_id"
        ]
        folder = SECRETS / f"approle-{service}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "role_id").write_text(str(role_id), encoding="utf-8")
        (folder / "secret_id").write_text(str(secret_id), encoding="utf-8")


def main() -> int:
    _engine(_admin_password())
    _approles()
    print(f"dynamic database credentials: {len(SERVICES)} AppRoles ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
