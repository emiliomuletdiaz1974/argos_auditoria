"""One database login user per service in the development environment (F09-04).

Each service connects as `login_<service>`, a member of its NOLOGIN role `svc_<service>` of
migration 0033, and never as the superuser. Until F09-05 makes them dynamic, the passwords are
fixed per environment:

    generate  before `compose up`: one random password per service, written to
              deploy/dev/secrets/db-<service> (gitignored) and mounted in its container as a
              secret file (ARGOS_DATABASE_PASSWORD_FILE);
    apply     after the migrations: creates or updates the login users with those passwords and
              stores each one in Vault KV (argos/database/<service>) for the operators.

Both phases are idempotent: an existing password file is kept.
"""

import argparse
import json
import os
import secrets
import stat
import sys
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql

from argos_common.config import get_config

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "deploy" / "dev" / "secrets"
# The services with a container that reaches the database, and the role each one is a member of.
SERVICES = {
    "api": "svc_api",
    "webhook": "svc_webhook",
    "challenge": "svc_challenge",
    "evidence": "svc_evidence",
    "ai_gateway": "svc_ai_gateway",
    "example": "svc_example",
}


def secret_file(service: str) -> Path:
    return SECRETS / f"db-{service}"


def generate() -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    # Only the owner walks into the directory; each file must still be readable by the container
    # user (10001), which sees the file through its bind mount and not through the directory.
    os.chmod(SECRETS, stat.S_IRWXU)
    for service in SERVICES:
        path = secret_file(service)
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def _store_in_vault(service: str, user: str, password: str) -> None:
    addr = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
    token = os.environ.get("VAULT_TOKEN", "root")  # development Vault: -dev-root-token-id=root
    body = json.dumps({"data": {"username": user, "password": password}}).encode()
    request = urllib.request.Request(  # noqa: S310 - fixed development address
        f"{addr}/v1/argos/data/database/{service}",
        data=body,
        method="POST",
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310
        pass


def apply() -> None:
    with psycopg.connect(get_config().DATABASE_URL, autocommit=True) as conn:
        for service, role in SERVICES.items():
            user = f"login_{service}"
            password = secret_file(service).read_text(encoding="utf-8").strip()
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            conn.execute(
                sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(user), sql.Literal(password)
                )
            )
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(user))
            )
            _store_in_vault(service, user, password)
    print(f"{len(SERVICES)} login users ready")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=("generate", "apply"))
    args = parser.parse_args()
    generate() if args.phase == "generate" else apply()
    return 0


if __name__ == "__main__":
    sys.exit(main())
