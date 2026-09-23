"""ARG-085 · dynamic database credentials against the development Vault and PostgreSQL (F09-05).

A Vault role with a 60 s TTL, member of `svc_example`: the credential works, is replaced at half
its life, the service keeps connecting after the rotation, and the first ephemeral user stops
working when it expires and disappears from `pg_roles`.
"""

import json
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from argos_common.dynamic_db import DynamicCredentials, VaultDatabaseSource, parse_service_file

pytestmark = pytest.mark.integration

VAULT = "http://127.0.0.1:8200"
ROOT = "root"  # development Vault started with -dev-root-token-id=root
DSN = "postgresql://127.0.0.1:55432/argos?service=argos&connect_timeout=5"


def _vault(method: str, path: str, body: dict[str, object] | None = None) -> None:
    request = urllib.request.Request(  # noqa: S310 - fixed development address
        f"{VAULT}/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-Vault-Token": ROOT, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310
        pass


@pytest.fixture
def short_role() -> Iterator[str]:
    name = f"svc-probe-{uuid.uuid4().hex[:6]}"
    _vault(
        "POST",
        f"db/roles/{name}",
        {
            "db_name": "argos",
            "default_ttl": "60s",
            "max_ttl": "60s",
            "creation_statements": [
                "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}'"
                " VALID UNTIL '{{expiration}}' IN ROLE svc_example;"
            ],
            "revocation_statements": ['DROP ROLE IF EXISTS "{{name}}";'],
        },
    )
    try:
        yield name
    finally:
        _vault("DELETE", f"db/roles/{name}")


def _who(dsn: str) -> tuple[str, bool]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT current_user, pg_has_role('svc_example', 'MEMBER')").fetchone()
    assert row is not None
    return str(row[0]), bool(row[1])


def _exists(migrated_db: str, user: str) -> bool:
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
    return row is not None


def test_a_credential_rotates_in_place_and_the_old_one_dies(
    short_role: str, tmp_path: Path, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_file = tmp_path / "pg_service.conf"
    monkeypatch.setenv("PGSERVICEFILE", str(service_file))
    credentials = DynamicCredentials(
        VaultDatabaseSource(VAULT, short_role, lambda: ROOT), service_file
    )
    credentials.start_blocking()
    first = parse_service_file(service_file)["argos"]
    assert _who(DSN) == (first["user"], True)

    time.sleep(31)
    credentials.step()
    second = parse_service_file(service_file)["argos"]
    assert second["user"] != first["user"]
    assert _who(DSN) == (second["user"], True), "new connections take the new credential"

    deadline = time.monotonic() + 60
    while _exists(migrated_db, first["user"]) and time.monotonic() < deadline:
        time.sleep(2)
    assert not _exists(migrated_db, first["user"]), "Vault revoked the expired user"
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            f"postgresql://{first['user']}:{first['password']}@127.0.0.1:55432/argos",
            connect_timeout=5,
        )
    assert _who(DSN) == (second["user"], True), "the service still connects after the rotation"


def _vault_json(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    request = urllib.request.Request(  # noqa: S310 - fixed development address
        f"{VAULT}/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-Vault-Token": ROOT, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw) if raw else {}


@pytest.mark.parametrize("role", ["svc-api", "svc-ai-gateway", "svc-evidence"])
def test_the_product_roles_issue_a_member_that_revocation_removes(
    role: str, migrated_db: str
) -> None:
    """The statements of platform/vault/database-engine.sh, as Vault runs them."""
    lease = _vault_json("GET", f"db/creds/{role}")
    data = lease["data"]
    assert isinstance(data, dict)
    user = str(data["username"])
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT rolvaliduntil IS NOT NULL, rolsuper, rolcreaterole FROM pg_roles"
            " WHERE rolname = %s",
            (user,),
        ).fetchone()
    assert row == (True, False, False)
    _vault_json("PUT", "sys/leases/revoke", {"lease_id": lease["lease_id"]})
    assert not _exists(migrated_db, user)
