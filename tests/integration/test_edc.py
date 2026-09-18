"""ARG-070 · a real credential published through the simulated EDC Management API."""

import json

import httpx
import psycopg
import pytest

from argos_common.journal_pg import PostgresJournal
from argos_evidence.dataspace.edc import EdcClient, EdcError, record_publication

from .test_credential import _issued
from .test_dossier import _store

pytestmark = pytest.mark.integration

EDC = "http://127.0.0.1:19193/management"
KEY = "dev-only-edc-key"
URL = "https://evidence.argos.example/credentials/"


def _credential(dsn: str) -> tuple[str, dict[str, object]]:
    credential_id, _ = _issued(dsn)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT object_key, version_id FROM argos.credentials WHERE id = %s", (credential_id,)
        ).fetchone()
    assert row is not None
    return credential_id, json.loads(_store().get(row[0], row[1]))


def _listed(kind: str) -> list[str]:
    response = httpx.post(f"{EDC}/v3/{kind}/request", json={}, headers={"x-api-key": KEY})
    return [item["@id"] for item in response.json()]


def test_the_credential_becomes_an_asset_with_its_policy_and_contract(migrated_db: str) -> None:
    credential_id, credential = _credential(migrated_db)
    record = EdcClient(EDC, KEY).publish_credential(credential, URL + credential_id, "retention")
    assert record.asset_id in _listed("assets")
    assert record.policy_id in _listed("policydefinitions")
    assert record.contract_id in _listed("contractdefinitions")
    again = EdcClient(EDC, KEY).publish_credential(credential, URL + credential_id, "retention")
    assert again == record


def test_the_publication_is_recorded_once_and_journaled(migrated_db: str) -> None:
    credential_id, credential = _credential(migrated_db)
    record = EdcClient(EDC, KEY).publish_credential(credential, URL, "no_redistribution")
    record_publication(migrated_db, credential_id, record, "user:dpo")
    record_publication(migrated_db, credential_id, record, "user:dpo")
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute("SELECT policy_choice FROM argos.dataspace_publications").fetchall()
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM argos.dataspace_publications")
    assert rows == [("no_redistribution",)]
    actions = [e.action for e in PostgresJournal(migrated_db).read(1)]
    assert actions.count("credential.published") == 1


def test_a_wrong_key_is_refused_by_the_connector(migrated_db: str) -> None:
    _, credential = _credential(migrated_db)
    with pytest.raises(EdcError, match="401"):
        EdcClient(EDC, "not-the-key").publish_credential(credential, URL, "use_only")


def test_the_dossier_cannot_leave_through_the_connector(migrated_db: str) -> None:
    store = _store()
    with psycopg.connect(migrated_db) as conn:
        _credential(migrated_db)
        row = conn.execute("SELECT json_key, json_version_id FROM argos.dossiers").fetchone()
    assert row is not None
    dossier = json.loads(store.get(row[0], row[1]))
    before = _listed("assets")
    with pytest.raises(EdcError, match="never a dossier"):
        EdcClient(EDC, KEY).publish_credential(dossier, URL, "use_only")
    assert _listed("assets") == before
