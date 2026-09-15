"""Simulated relational sources (F02-04): reachable, read-only accounts, server-side logs."""

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import hvac
import psycopg
import pymysql
import pytest

from argos_common.secret_stores import VaultSecretStore

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
CATALOG: list[dict[str, Any]] = json.loads(
    (ROOT / "deploy" / "dev" / "sources" / "systems.json").read_text(encoding="utf-8")
)["systems"]
DEV_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy" / "dev" / "compose.yaml")]


def _system(name: str) -> dict[str, Any]:
    return next(s for s in CATALOG if s["name"] == name)


def test_catalog_ids_are_unique_uuids() -> None:
    ids = [str(uuid.UUID(s["id"])) for s in CATALOG]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("name", ["dev-source-postgres", "dev-source-mariadb"])
def test_system_is_registered_with_a_secret_reference_only(name: str) -> None:
    system = _system(name)
    with psycopg.connect(DEV_DSN) as conn:
        row = conn.execute(
            "SELECT kind, environment, connection FROM argos.systems WHERE id = %s", (system["id"],)
        ).fetchone()
    assert row is not None
    kind, environment, connection = row
    assert (kind, environment) == (system["kind"], "development")
    assert connection["secret"] == f"connectors/{system['id']}"
    assert "url" not in json.dumps(connection) and "password" not in json.dumps(connection)


def test_connector_sdk_policy_reads_source_credentials() -> None:
    root = hvac.Client(url=VAULT, token="root")
    token = root.auth.token.create(policies=["svc-connector-sdk"], ttl="5m")["auth"]["client_token"]
    system_id = _system("dev-source-postgres")["id"]
    secret = VaultSecretStore(VAULT, str(token)).read(f"connectors/{system_id}")
    assert secret["url"].startswith("postgresql+psycopg://argos_ro@")
    assert len(bytes.fromhex(secret["hash_key"])) == 32


def test_postgres_account_reads_but_cannot_write() -> None:
    dsn = "postgresql://argos_ro@127.0.0.1:55433/clinic"
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT count(*) FROM clinic.patients").fetchone()
        assert row is not None and row[0] >= 5000
    with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("DELETE FROM clinic.consents")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM clinic.consents")


def test_postgres_logs_every_statement_with_its_user() -> None:
    with psycopg.connect("postgresql://argos_ro@127.0.0.1:55433/clinic") as conn:
        conn.execute("SELECT 'argos-log-probe'")
    logs = subprocess.run(  # noqa: S603 - fixed docker compose arguments, no external input
        [*COMPOSE, "logs", "--since", "5m", "source-postgres"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert any("user=argos_ro" in line and "argos-log-probe" in line for line in logs.splitlines())


def test_mariadb_account_reads_but_cannot_write() -> None:
    conn = pymysql.connect(
        host="127.0.0.1", port=53306, user="argos_ro", password="", database="billing"
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM invoices")
            row = cur.fetchone()
            assert row is not None and row[0] >= 3000
            with pytest.raises(pymysql.err.OperationalError):
                cur.execute("DELETE FROM invoices")
    finally:
        conn.close()


def test_mariadb_general_log_goes_to_a_table() -> None:
    conn = pymysql.connect(host="127.0.0.1", port=53306, user="root", password="")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT @@general_log, @@log_output")
            assert cur.fetchone() == (1, "TABLE")
    finally:
        conn.close()


@pytest.mark.heavy
def test_mssql_login_reads_but_cannot_write() -> None:
    import pymssql

    conn = pymssql.connect(
        server="127.0.0.1",
        port="51433",
        user="argos_ro",
        password="Dev-Only-Ro-2026",
        database="erp",
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM dbo.staff")
        row = cur.fetchone()
        assert row is not None and row[0] >= 500
        with pytest.raises(pymssql.Error):
            cur.execute("DELETE FROM dbo.staff")
            conn.commit()
    finally:
        conn.close()


@pytest.mark.heavy
def test_oracle_user_reads_but_cannot_write() -> None:
    import oracledb

    with oracledb.connect(
        user="argos_ro", password="dev-only-ro", dsn="127.0.0.1:51521/FREEPDB1"
    ) as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM his_owner.encounters")
        row = cur.fetchone()
        assert row is not None and row[0] >= 2000
        with pytest.raises(oracledb.DatabaseError):
            cur.execute("DELETE FROM his_owner.encounters")
