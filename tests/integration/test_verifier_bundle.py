"""ARG-069 · a real campaign exported as a bundle verifies end to end, time stamp included."""

import base64
import datetime as dt
import json
import os

import httpx
import psycopg
import pytest

from argos_common.release import VaultTransitSigner
from argos_evidence.bundle import export_bundle
from argos_evidence.core.envelope import key_id
from argos_evidence.core.integrity import file_digest
from argos_evidence.credential.did import did_document, did_web
from argos_evidence.credential.issue import issue_credential, status_list_credential
from argos_evidence.dossier import write_dossier
from argos_evidence.journal import report_key
from argos_evidence.tsa import enqueue, http_transport, process_queue, stamp_of
from argos_verifier.checks import Trust, verify_bundle

from .test_dossier import URL, _campaign, _roots, _store

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
TSA = os.environ.get("ARGOS_TEST_TSA", "http://127.0.0.1:3180")
ISSUER = did_web("evidence.argos.example")
STATUS = "https://evidence.argos.example/status"


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def trust() -> Trust:
    """What a third party trusts: the development evidence key and the development TSA root."""
    signer = VaultTransitSigner(VAULT, "root", key="argos-evidence")
    return Trust(frozenset({key_id(signer.public_key())}), (httpx.get(f"{TSA}/ca.pem").text,))


def _exported(dsn: str) -> dict[str, object]:
    store = _store()
    signer = VaultTransitSigner(VAULT, "root", key="argos-evidence")
    campaign_id = _campaign(dsn, store)
    process_queue(dsn, store, http_transport(TSA), _roots(), _until())
    dossier = write_dossier(dsn, store, campaign_id, URL, _until())
    credential = issue_credential(dsn, store, signer, ISSUER, STATUS, dossier.sha256, _until())
    return export_bundle(
        dsn,
        store,
        dossier.sha256,
        did_document=did_document(ISSUER, signer.public_key()),
        status_list=status_list_credential(dsn, signer, ISSUER, STATUS, credential.status_list),
        tsa_roots_pem=[httpx.get(f"{TSA}/ca.pem").text],
    )


def test_an_exported_campaign_verifies_with_every_check(migrated_db: str) -> None:
    bundle = _exported(migrated_db)
    report = verify_bundle(bundle, trust())
    statuses = {c.name: c.status for c in report.checks}
    assert report.ok, [c for c in report.checks if c.status != "passed"]
    assert set(statuses.values()) == {"passed"}
    assert statuses["timestamp"] == "passed"
    assert len([n for n in statuses if n.startswith("artifact_inclusion")]) == 2


def test_the_bundle_is_plain_json_a_third_party_can_carry(migrated_db: str) -> None:
    bundle = _exported(migrated_db)
    assert json.loads(json.dumps(bundle)) == bundle
    assert bundle["schema"] == "argos/verification-bundle/1"


def test_a_real_token_over_another_object_fails_the_time_stamp_check(migrated_db: str) -> None:
    bundle = _exported(migrated_db)
    store = _store()
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT id::text FROM argos.campaigns").fetchone()
    assert row is not None
    report = report_key(row[0])
    version = store.version_of(report)
    enqueue(migrated_db, report, version, file_digest(store.get(report, version)))
    process_queue(migrated_db, store, http_transport(TSA), _roots(), _until())
    stamp = stamp_of(migrated_db, report)
    assert stamp is not None and stamp.token_key and stamp.token_version_id
    token = store.get(stamp.token_key, stamp.token_version_id)
    bundle["timestamp_token"] = base64.b64encode(token).decode()
    failed = {c.name for c in verify_bundle(bundle, trust()).checks if c.status == "failed"}
    assert failed == {"timestamp"}


def test_an_artifact_changed_in_the_bundle_is_pointed_at(migrated_db: str) -> None:
    bundle = _exported(migrated_db)
    artifacts = bundle["artifacts"]
    assert isinstance(artifacts, list)
    raw = bytearray(base64.b64decode(artifacts[1]["artifact"]))
    raw[-3] ^= 0x01
    artifacts[1]["artifact"] = base64.b64encode(bytes(raw)).decode()
    failed = {c.name for c in verify_bundle(bundle, trust()).checks if c.status == "failed"}
    assert failed == {"artifact_inclusion[1]"}
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.evidence_index").fetchone() == (2,)
