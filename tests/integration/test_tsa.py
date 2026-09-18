"""ARG-065 · RFC 3161 stamps from the development TSA: queue, verification and isolated mode."""

import datetime as dt
import hashlib
import os
import uuid
from typing import Any

import boto3
import httpx
import psycopg
import pytest
from cryptography import x509

from argos_challenges.seal import seal_campaign
from argos_challenges.store import create_campaign
from argos_common.release import VaultTransitSigner
from argos_evidence.core.timestamp import TimestampRejectedError
from argos_evidence.merkle import build_tree
from argos_evidence.roots import record_root
from argos_evidence.signing import sign_campaign_root
from argos_evidence.tsa import (
    accept_reply,
    export_requests,
    http_transport,
    import_replies,
    process_queue,
    stamp_of,
)
from argos_evidence.worm import WormStore, ensure_buckets

pytestmark = pytest.mark.integration

TSA = os.environ.get("ARGOS_TEST_TSA", "http://127.0.0.1:3180")
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


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


def _roots() -> list[x509.Certificate]:
    return [x509.load_pem_x509_certificate(httpx.get(f"{TSA}/ca.pem").content)]


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _signed(dsn: str, store: WormStore) -> str:
    """A sealed campaign whose root is signed: the signature enqueues its own stamp."""
    campaign_id = create_campaign(dsn, "Campaña sellada en el tiempo", {}, "user:campaign-manager")
    seal_campaign(dsn, campaign_id)
    leaves = [hashlib.sha256(uuid.uuid4().bytes).digest() for _ in range(3)]
    record_root(dsn, campaign_id, build_tree(leaves), f"campaigns/{campaign_id}/tree.json")
    signer = VaultTransitSigner(VAULT, "root", key="argos-evidence")
    return sign_campaign_root(dsn, store, signer, campaign_id, None, _until()).key


def _failing(_: bytes) -> bytes:
    raise httpx.ConnectError("no window to the TSA")


def test_signing_enqueues_the_stamp_and_the_state_is_visible(migrated_db: str) -> None:
    key = _signed(migrated_db, _store())
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None
    assert stamp.status == "queued"
    assert stamp.token_key is None


def test_the_queue_stamps_with_a_verified_token_kept_in_the_worm(migrated_db: str) -> None:
    store = _store()
    key = _signed(migrated_db, store)
    summary = process_queue(migrated_db, store, http_transport(TSA), _roots(), _until())
    assert summary.stamped == [key]
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None and stamp.status == "stamped"
    assert stamp.policy == "1.2.3.4.1"
    assert stamp.gen_time is not None
    assert stamp.token_key == f"{key}.tsr"
    assert store.get(stamp.token_key, stamp.token_version_id)


def test_a_failed_attempt_keeps_the_object_queued_and_a_retry_stamps_it(migrated_db: str) -> None:
    store = _store()
    key = _signed(migrated_db, store)
    first = process_queue(migrated_db, store, _failing, _roots(), _until())
    assert first.failed == [key]
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None
    assert (stamp.status, stamp.attempts) == ("queued", 1)
    assert "no window" in (stamp.last_error or "")
    second = process_queue(migrated_db, store, http_transport(TSA), _roots(), _until())
    assert second.stamped == [key]


def test_a_token_for_another_object_is_rejected(migrated_db: str) -> None:
    store = _store()
    first, other = _signed(migrated_db, store), _signed(migrated_db, store)
    requests = export_requests(migrated_db, store)
    reply_for_first = http_transport(TSA)(requests[first])
    with pytest.raises(TimestampRejectedError):
        accept_reply(migrated_db, store, other, reply_for_first, _roots(), _until())
    stamp = stamp_of(migrated_db, other)
    assert stamp is not None and stamp.status == "queued"


def test_isolated_mode_exports_requests_and_imports_replies(migrated_db: str) -> None:
    store = _store()
    key = _signed(migrated_db, store)
    requests = export_requests(migrated_db, store)
    assert key in requests
    outside = http_transport(TSA)  # stands for the stamping done outside the appliance
    replies = {k: outside(v) for k, v in requests.items()}
    results = import_replies(migrated_db, store, replies, _roots(), _until())
    assert results[key] is None
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None and stamp.status == "stamped"


def test_an_imported_reply_to_an_older_request_is_rejected(migrated_db: str) -> None:
    store = _store()
    key = _signed(migrated_db, store)
    stale = export_requests(migrated_db, store)[key]
    export_requests(migrated_db, store)  # a new export replaces the nonce
    results: dict[str, Any] = import_replies(
        migrated_db, store, {key: http_transport(TSA)(stale)}, _roots(), _until()
    )
    assert "Nonce" in str(results[key])
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None and stamp.status == "queued"


def test_a_stamped_entry_cannot_change_or_disappear(migrated_db: str) -> None:
    store = _store()
    key = _signed(migrated_db, store)
    process_queue(migrated_db, store, http_transport(TSA), _roots(), _until())
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.tsa_queue SET status = 'queued' WHERE object_key = %s", (key,))
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.tsa_queue")
