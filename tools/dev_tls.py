"""Internal certificates of the development environment (F09-06, ARG-083).

Run after `deploy/dev/vault/setup.sh`, before the services start:

1. the AppRole of `cert-issuer`, which may only issue from `pki_int/issue/argos-svc`; its
   `role_id` and `secret_id` go to `deploy/dev/secrets/approle-cert-issuer/`, mounted read-only;
2. the client certificate of the host (`argos-dev`), for tests and tools that connect from outside
   the containers to PostgreSQL and NATS: `deploy/dev/secrets/tls-host/` (gitignored).

The certificate of each service is not issued here: `cert-issuer` issues and renews it inside its
own volume, which no other container mounts.
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from argos_tls.issuer import Request, Vault, renew

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "deploy" / "dev" / "secrets"
VAULT = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
TOKEN = os.environ.get("VAULT_TOKEN", "root")  # development Vault: -dev-root-token-id=root
HOST = Request("tls-host", ("argos-dev", "localhost", "127.0.0.1"))


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


def issuer_approle() -> None:
    methods = _vault("GET", "sys/auth")
    if "approle/" not in methods.get("data", methods):
        _vault("POST", "sys/auth/approle", {"type": "approle"})
    _vault(
        "POST",
        "auth/approle/role/argos-cert-issuer",
        {
            "token_policies": ["argos-cert-issuer"],
            "token_ttl": "1h",
            "token_max_ttl": "1h",
            "token_no_default_policy": True,
        },
    )
    role_id = _vault("GET", "auth/approle/role/argos-cert-issuer/role-id")["data"]["role_id"]
    secret_id = _vault("POST", "auth/approle/role/argos-cert-issuer/secret-id", {})["data"][
        "secret_id"
    ]
    folder = SECRETS / "approle-cert-issuer"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "role_id").write_text(str(role_id), encoding="utf-8")
    (folder / "secret_id").write_text(str(secret_id), encoding="utf-8")


def host_certificate() -> None:
    # A new certificate on every run: Vault in development forgets its CA when it restarts.
    for name in ("tls.crt", "tls.key", "ca.crt"):
        (SECRETS / HOST.folder / name).unlink(missing_ok=True)
    renew(Vault(VAULT, lambda: TOKEN), SECRETS, [HOST], dt.datetime.now(dt.UTC))


def main() -> int:
    issuer_approle()
    host_certificate()
    print("internal certificates: cert-issuer AppRole and host certificate ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
