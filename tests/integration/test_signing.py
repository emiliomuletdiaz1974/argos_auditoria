"""ARG-064 · a sealed campaign's root signed with the Vault key and kept in the WORM."""

import datetime as dt
import hashlib
import json
import os
import uuid

import boto3
import psycopg
import pytest

from argos_challenges.seal import seal_campaign
from argos_challenges.store import create_campaign
from argos_common.journal_pg import PostgresJournal
from argos_common.release import VaultTransitSigner
from argos_evidence.core.envelope import verify_envelope
from argos_evidence.merkle import build_tree
from argos_evidence.roots import record_root
from argos_evidence.signing import SigningError, sign_campaign_root, signature_key
from argos_evidence.worm import WormStore, ensure_buckets

from .campaign_helpers import running

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
HEAD = {"seq": 1, "entry_hash": "e" * 64}


def _store() -> WormStore:
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7075",
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )
    ensure_buckets(client, default_retention_days=1)
    return WormStore(client)


def _signer() -> VaultTransitSigner:
    return VaultTransitSigner(VAULT, "root", key="argos-evidence")


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _campaign(dsn: str, sealed: bool = True, with_root: bool = True) -> str:
    campaign_id = create_campaign(dsn, "Campaña firmada", {}, "user:campaign-manager")
    if sealed:
        running(dsn, campaign_id)
        seal_campaign(dsn, campaign_id)
    if with_root:
        leaves = [hashlib.sha256(uuid.uuid4().bytes).digest() for _ in range(3)]
        record_root(dsn, campaign_id, build_tree(leaves), f"campaigns/{campaign_id}/tree.json")
    return campaign_id


def test_a_root_is_signed_stored_and_verifiable(migrated_db: str) -> None:
    store, signer = _store(), _signer()
    campaign_id = _campaign(migrated_db)
    record = sign_campaign_root(migrated_db, store, signer, campaign_id, HEAD, _until())
    assert record.key == signature_key(campaign_id)
    body = store.get(record.key, record.version_id)
    assert record.sha256 == hashlib.sha256(body).hexdigest()
    assert verify_envelope(body, signer.public_key())
    payload = json.loads(body)["payload"]
    assert payload["non_production"] is True
    assert payload["journal_head"] == HEAD
    with psycopg.connect(migrated_db) as conn:
        seal = conn.execute(
            "SELECT seal FROM argos.campaigns WHERE id = %s", (campaign_id,)
        ).fetchone()
    assert seal is not None and payload["campaign_seal"] == seal[0]


def test_signing_twice_returns_the_first_signature(migrated_db: str) -> None:
    store, signer = _store(), _signer()
    campaign_id = _campaign(migrated_db)
    first = sign_campaign_root(migrated_db, store, signer, campaign_id, HEAD, _until())
    again = sign_campaign_root(migrated_db, store, signer, campaign_id, HEAD, _until())
    assert again == first


def test_the_signature_is_journaled(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db)
    record = sign_campaign_root(migrated_db, _store(), _signer(), campaign_id, HEAD, _until())
    entries = [
        e for e in PostgresJournal(migrated_db).read(1) if e.action == "campaign.root_signed"
    ]
    assert len(entries) == 1
    assert campaign_id in entries[0].payload_canon
    assert record.sha256 in entries[0].payload_canon


def test_an_unsealed_campaign_or_one_without_root_is_not_signed(migrated_db: str) -> None:
    store, signer = _store(), _signer()
    with pytest.raises(SigningError, match="sealed"):
        sign_campaign_root(
            migrated_db, store, signer, _campaign(migrated_db, sealed=False), HEAD, _until()
        )
    with pytest.raises(SigningError, match="root"):
        sign_campaign_root(
            migrated_db, store, signer, _campaign(migrated_db, with_root=False), HEAD, _until()
        )


def test_the_signature_row_is_written_once(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db)
    sign_campaign_root(migrated_db, _store(), _signer(), campaign_id, HEAD, _until())
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.campaign_signatures SET non_production = false")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.campaign_signatures")
