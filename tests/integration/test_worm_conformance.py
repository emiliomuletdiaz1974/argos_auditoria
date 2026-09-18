"""ARG-061 · conformance of the WORM store (ADR-0010): the store is chosen by this test.

It runs against the real store of the development environment, not a double. A version written
with a compliance-mode retention must survive three attempts: deleting it, overwriting it and
shortening its retention. In S3 a plain PUT on the same key creates a new version and never
touches the old one, so "overwrite" is checked as: the conditional write the client uses is
refused, and whatever else is written, the locked version stays byte-identical and locked.
"""

import datetime as dt
import hashlib
import uuid
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from argos_evidence.worm import (
    EVIDENCE_BUCKET,
    WORKING_BUCKET,
    WormAlreadyStoredError,
    WormStore,
    ensure_buckets,
)

pytestmark = pytest.mark.integration

ENDPOINT = "http://127.0.0.1:7075"
ACCESS_KEY = "dev-only-evidence"
SECRET_KEY = "dev-only-evidence-secret"  # noqa: S105 - development store, trivial on purpose


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
    )


@pytest.fixture
def store() -> WormStore:
    client = _client()
    ensure_buckets(client, default_retention_days=1)
    return WormStore(client)


def _key() -> str:
    return f"conformance/{uuid.uuid4()}.json"


def _until(minutes: int = 10) -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0) + dt.timedelta(minutes=minutes)


def _denied(call: Any) -> str:
    with pytest.raises(ClientError) as caught:
        call()
    return str(caught.value.response["Error"]["Code"])


def test_a_locked_version_cannot_be_deleted(store: WormStore) -> None:
    stored = store.put_immutable(_key(), b'{"verdict":"compliant"}', _until())
    raw = _client()
    assert (
        _denied(
            lambda: raw.delete_object(
                Bucket=EVIDENCE_BUCKET, Key=stored.key, VersionId=stored.version_id
            )
        )
        == "AccessDenied"
    )
    assert (
        _denied(
            lambda: raw.delete_object(
                Bucket=EVIDENCE_BUCKET,
                Key=stored.key,
                VersionId=stored.version_id,
                BypassGovernanceRetention=True,
            )
        )
        == "AccessDenied"
    )
    assert store.get(stored.key, stored.version_id) == b'{"verdict":"compliant"}'


def test_a_locked_version_cannot_be_overwritten(store: WormStore) -> None:
    body = b'{"verdict":"non_compliant"}'
    stored = store.put_immutable(_key(), body, _until())
    with pytest.raises(WormAlreadyStoredError):
        store.put_immutable(stored.key, b"tampered", _until())
    _client().put_object(Bucket=EVIDENCE_BUCKET, Key=stored.key, Body=b"tampered")
    assert store.get(stored.key, stored.version_id) == body
    assert store.retention(stored.key, stored.version_id)[0] == "COMPLIANCE"


def test_a_retention_cannot_be_shortened_or_relaxed(store: WormStore) -> None:
    until = _until()
    stored = store.put_immutable(_key(), b"artifact", until)
    raw = _client()
    for mode, date in (("COMPLIANCE", until - dt.timedelta(minutes=5)), ("GOVERNANCE", until)):
        assert (
            _denied(
                lambda mode=mode, date=date: raw.put_object_retention(
                    Bucket=EVIDENCE_BUCKET,
                    Key=stored.key,
                    VersionId=stored.version_id,
                    Retention={"Mode": mode, "RetainUntilDate": date},
                    BypassGovernanceRetention=True,
                )
            )
            == "AccessDenied"
        )
    assert store.retention(stored.key, stored.version_id) == ("COMPLIANCE", until)


def test_even_a_write_without_lock_headers_is_locked_by_the_bucket_default(
    store: WormStore,
) -> None:
    # VersityGW enforces the bucket default without reporting it through GetObjectRetention
    # (AWS reports it). The guarantee is what counts: the version cannot be deleted.
    key = _key()
    raw = _client()
    version = raw.put_object(Bucket=EVIDENCE_BUCKET, Key=key, Body=b"raw")["VersionId"]
    assert (
        _denied(lambda: raw.delete_object(Bucket=EVIDENCE_BUCKET, Key=key, VersionId=version))
        == "AccessDenied"
    )


def test_the_client_rereads_and_returns_the_hash(store: WormStore) -> None:
    body = b'{"artifact":1}'
    stored = store.put_immutable(_key(), body, _until())
    assert stored.sha256 == hashlib.sha256(body).hexdigest()
    assert store.get(stored.key) == body


def test_the_buckets_are_set_up_idempotently() -> None:
    client = _client()
    ensure_buckets(client, default_retention_days=1)
    ensure_buckets(client, default_retention_days=1)
    lock = client.get_object_lock_configuration(Bucket=EVIDENCE_BUCKET)["ObjectLockConfiguration"]
    assert lock["ObjectLockEnabled"] == "Enabled"
    assert lock["Rule"]["DefaultRetention"]["Mode"] == "COMPLIANCE"
    assert client.get_bucket_versioning(Bucket=WORKING_BUCKET)["Status"] == "Enabled"
