"""The simulated sources contain what the inventory ground truth expects (F03-00)."""

import importlib.util
import json
import re

import psycopg
import pymysql
import pytest
from fixtures.ground_truth import load_ground_truth

from .sources import ROOT

pytestmark = pytest.mark.integration

POSTGRES_OWNER = "postgresql://owner@127.0.0.1:55433/clinic"
SOURCES = ROOT / "deploy" / "dev" / "sources"
DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
COLUMNS_SQL = (
    "SELECT concat(table_schema, '.', table_name), column_name FROM information_schema.columns "
    "WHERE table_schema = %s ORDER BY table_name, ordinal_position"
)

_spec = importlib.util.spec_from_file_location("prepare", ROOT / "tools" / "prepare_dev_sources.py")
assert _spec is not None and _spec.loader is not None
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)


def _group(rows: list[tuple[str, str]]) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for table, column in rows:
        tables.setdefault(table, []).append(column)
    return tables


def _dni_ok(value: str) -> bool:
    match = re.fullmatch(r"(\d{8})([A-Z])", value)
    return bool(match) and DNI_LETTERS[int(match[1]) % 23] == match[2]


def _iban_ok(value: str) -> bool:
    return bool(re.fullmatch(r"ES\d{22}", value)) and int(value[4:] + "1428" + value[2:4]) % 97 == 1


def test_postgres_tables_and_columns_match_the_ground_truth() -> None:
    with psycopg.connect(POSTGRES_OWNER) as conn:
        rows = conn.execute(COLUMNS_SQL, ("clinic",)).fetchall()
    assert _group(rows) == load_ground_truth().tables("dev-source-postgres")


def test_mariadb_tables_and_columns_match_the_ground_truth() -> None:
    conn = pymysql.connect(host="127.0.0.1", port=53306, user="root", password="")
    try:
        with conn.cursor() as cur:
            cur.execute(COLUMNS_SQL, ("billing",))
            rows = [(str(t), str(c)) for t, c in cur.fetchall()]
    finally:
        conn.close()
    assert _group(rows) == load_ground_truth().tables("dev-source-mariadb")


def test_identifier_columns_hold_formally_valid_synthetic_values() -> None:
    with psycopg.connect(POSTGRES_OWNER) as conn:
        postgres = conn.execute("SELECT dni_number, iban FROM clinic.patient_documents").fetchall()
    conn2 = pymysql.connect(host="127.0.0.1", port=53306, user="root", password="")
    try:
        with conn2.cursor() as cur:
            cur.execute("SELECT dni_number, iban FROM billing.patient_mirror")
            mariadb = list(cur.fetchall())
    finally:
        conn2.close()
    for rows in (postgres, mariadb):
        assert len(rows) == 1000
        assert all(_dni_ok(dni) and _iban_ok(iban) for dni, iban in rows)
        assert all(99990000 < int(dni[:8]) <= 99991000 for dni, _ in rows)


def test_engine_link_and_model_file_are_in_place() -> None:
    with psycopg.connect(POSTGRES_OWNER) as conn:
        options = conn.execute(
            "SELECT srvoptions FROM pg_foreign_server WHERE srvname = 'billing_link'"
        ).fetchone()
    assert options is not None and "host=source-mariadb" in options[0]
    manifest = prepare.tree_manifest(SOURCES / "files" / "clinical")
    assert "admin/models/readmission_v3.onnx" in manifest
    catalog = json.loads((SOURCES / "systems.json").read_text(encoding="utf-8"))["systems"]
    aliases = {s["name"]: s["config"].get("host_aliases", []) for s in catalog}
    assert "source-mariadb" in aliases["dev-source-mariadb"]
    assert "source-postgres" in aliases["dev-source-postgres"]
