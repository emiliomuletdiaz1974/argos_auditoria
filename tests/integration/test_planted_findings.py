"""F05-01 · the simulated sources hold the facts the campaign ground truth relies on."""

import json
from datetime import UTC, datetime, timedelta

import psycopg
import pymysql
import pytest

from argos_inventory.catalog.treatments import parse_treatments

from .sources import ROOT

pytestmark = pytest.mark.integration

POSTGRES_OWNER = "postgresql://owner@127.0.0.1:55433/clinic"
CLIENT_DATA = ROOT / "deploy" / "dev" / "opa" / "client" / "data.json"
TREATMENTS = ROOT / "deploy" / "dev" / "ropa" / "treatments.csv"
CAMPAIGN_DATE = datetime(2026, 9, 16, tzinfo=UTC)


def _mariadb() -> pymysql.connections.Connection:
    return pymysql.connect(host="127.0.0.1", port=53306, user="root", password="")


def _variables(names: tuple[str, ...]) -> dict[str, str]:
    conn = _mariadb()
    try:
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(names))
            cur.execute(f"SHOW GLOBAL VARIABLES WHERE Variable_name IN ({placeholders})", names)
            return {str(name): str(value) for name, value in cur.fetchall()}
    finally:
        conn.close()


def _client() -> dict[str, dict[str, object]]:
    return json.loads(CLIENT_DATA.read_text(encoding="utf-8"))


def test_postgres_logs_statements_without_transport_encryption() -> None:
    with psycopg.connect(POSTGRES_OWNER) as conn:
        assert conn.execute("SHOW ssl").fetchone() == ("off",)
        assert conn.execute("SHOW log_statement").fetchone() == ("all",)


def test_mariadb_logs_without_encryption_at_rest_or_in_transit() -> None:
    names = ("general_log", "innodb_encrypt_tables", "require_secure_transport")
    assert _variables(names) == {
        "general_log": "ON",
        "innodb_encrypt_tables": "OFF",
        "require_secure_transport": "OFF",
    }


def test_the_planted_billing_account_reads_the_health_replica_without_an_authorised_profile() -> (
    None
):
    conn = _mariadb()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW GRANTS FOR 'billing_analyst'@'%'")
            grants = " ".join(str(row[0]) for row in cur.fetchall())
    finally:
        conn.close()
    assert "SELECT ON `billing`.`patient_mirror`" in grants
    client = _client()
    profile = client["identity_profiles"]["billing_analyst"]
    assert profile not in client["authorized_profiles"]["special_category.health"]
    for identity in ("argos_ro", "clinic_admin"):
        authorised = client["authorized_profiles"]["special_category.health"]
        assert client["identity_profiles"][identity] in authorised


def test_records_older_than_the_declared_terms_exist() -> None:
    schedule = _client()["retention_schedule"]
    his_limit = CAMPAIGN_DATE - timedelta(days=int(schedule["T-HIS"]["days"]))  # type: ignore[index]
    billing_limit = CAMPAIGN_DATE - timedelta(days=int(schedule["T-BILLING"]["days"]))  # type: ignore[index]
    with psycopg.connect(POSTGRES_OWNER) as conn:
        row = conn.execute(
            "SELECT count(*) FROM clinic.patients WHERE created_at < %s", (his_limit,)
        ).fetchone()
    assert row is not None and row[0] > 0
    conn2 = _mariadb()
    try:
        with conn2.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM billing.invoices WHERE issued_at < %s",
                (billing_limit.replace(tzinfo=None),),
            )
            (old_invoices,) = cur.fetchone()
    finally:
        conn2.close()
    assert old_invoices > 0


def test_the_record_of_processing_declares_both_systems_and_plants_a_missing_legal_basis() -> None:
    rows = {row.id: row for row in parse_treatments(TREATMENTS.read_bytes())}
    assert set(rows) == {"T-HIS", "T-BILLING"}
    assert rows["T-HIS"].legal_basis and rows["T-HIS"].retention
    assert rows["T-BILLING"].legal_basis == "" and rows["T-BILLING"].retention
    assert rows["T-HIS"].systems == ("dev-source-postgres",)
    assert rows["T-BILLING"].systems == ("dev-source-mariadb",)
