"""ARG-068 · the credential of a real dossier: issued with the Vault key, verified, revoked."""

import datetime as dt
import json
import os

import psycopg
import pytest

from argos_common.release import VaultTransitSigner
from argos_evidence.artifacts import personal_identifiers
from argos_evidence.credential.did import did_document, did_web
from argos_evidence.credential.issue import (
    CredentialError,
    issue_credential,
    revoke_credential,
    status_list_credential,
)
from argos_evidence.credential.verify import verify_credential
from argos_evidence.dossier import write_dossier

from .test_dossier import URL, _campaign, _store

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
ISSUER = did_web("evidence.argos.example")
STATUS = "https://evidence.argos.example/status"


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _signer() -> VaultTransitSigner:
    return VaultTransitSigner(VAULT, "root", key="argos-evidence")


def _issued(dsn: str) -> tuple[str, str]:
    store = _store()
    campaign_id = _campaign(dsn, store)
    dossier = write_dossier(dsn, store, campaign_id, URL, _until())
    record = issue_credential(dsn, store, _signer(), ISSUER, STATUS, dossier.sha256, _until())
    return record.credential_id, dossier.sha256


def test_a_credential_is_issued_for_the_dossier_and_verifies(migrated_db: str) -> None:
    store, signer = _store(), _signer()
    campaign_id = _campaign(migrated_db, store)
    dossier = write_dossier(migrated_db, store, campaign_id, URL, _until())
    record = issue_credential(migrated_db, store, signer, ISSUER, STATUS, dossier.sha256, _until())
    credential = json.loads(store.get(record.key, record.version_id))
    assert credential["issuer"] == ISSUER
    assert credential["credentialSubject"]["dossierSha256"] == dossier.sha256
    assert credential["credentialSubject"]["nonProduction"] is True
    assert personal_identifiers(credential["credentialSubject"]) == []
    status = status_list_credential(migrated_db, signer, ISSUER, STATUS, record.status_list)
    check = verify_credential(credential, did_document(ISSUER, signer.public_key()), status)
    assert check.valid, check.reasons
    again = issue_credential(migrated_db, store, signer, ISSUER, STATUS, dossier.sha256, _until())
    assert again == record


def test_revoking_flips_the_status_bit_and_leaves_the_credential_untouched(
    migrated_db: str,
) -> None:
    store, signer = _store(), _signer()
    credential_id, _ = _issued(migrated_db)
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT object_key, version_id, status_list FROM argos.credentials WHERE id = %s",
            (credential_id,),
        ).fetchone()
    assert row is not None
    before = store.get(row[0], row[1])
    revoke_credential(migrated_db, credential_id, "expediente sustituido", "user:dpo")
    assert store.get(row[0], row[1]) == before
    status = status_list_credential(migrated_db, signer, ISSUER, STATUS, int(row[2]))
    check = verify_credential(json.loads(before), did_document(ISSUER, signer.public_key()), status)
    assert check.reasons == ["revoked"]


def test_a_revocation_needs_a_reason_and_is_written_once(migrated_db: str) -> None:
    credential_id, _ = _issued(migrated_db)
    with pytest.raises(CredentialError, match="reason"):
        revoke_credential(migrated_db, credential_id, " ", "user:dpo")
    revoke_credential(migrated_db, credential_id, "error en el alcance", "user:dpo")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.credential_revocations")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.credentials SET sha256 = repeat('0', 64)")


def test_there_is_no_credential_without_a_dossier(migrated_db: str) -> None:
    with pytest.raises(CredentialError, match="no dossier"):
        issue_credential(migrated_db, _store(), _signer(), ISSUER, STATUS, "0" * 64, _until())
