"""WORM store of the evidence (ARG-061, ADR-0010).

An S3-compatible store with object lock in compliance mode: while a version is
retained, nobody, the store administrator included, can remove it, replace its
bytes or shorten its retention. The store was chosen by the conformance test in
tests/integration/test_worm_conformance.py, not by its documentation.

This client can write once and read. It has no primitive to take anything
away, and tests/architecture/test_worm_has_no_delete.py keeps it that way.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

EVIDENCE_BUCKET = "evidence"
WORKING_BUCKET = "working"
LOCK_MODE = "COMPLIANCE"
_ALREADY_THERE = {"PreconditionFailed", "ConditionalRequestConflict"}
_BUCKET_EXISTS = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


class WormError(Exception):
    """The store did not do what the evidence needs."""


class WormAlreadyStoredError(WormError):
    """The key already holds a version: evidence is written once."""


class WormIntegrityError(WormError):
    """What the store gives back is not what was written."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    version_id: str
    sha256: str
    retain_until: dt.datetime


class WormStore:
    """Write-once, read-many access to the evidence bucket."""

    def __init__(self, client: Any, bucket: str = EVIDENCE_BUCKET) -> None:
        self._client = client
        self._bucket = bucket

    def put_immutable(self, key: str, data: bytes, retain_until: dt.datetime) -> StoredObject:
        """Write ``data`` under a new key, locked until ``retain_until``, and read it back."""
        if retain_until.tzinfo is None:
            raise ValueError("retain_until must carry a time zone")
        if retain_until <= dt.datetime.now(dt.UTC):
            raise ValueError("retain_until must be in the future")
        digest = hashlib.sha256(data).digest()
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
                ObjectLockMode=LOCK_MODE,
                ObjectLockRetainUntilDate=retain_until,
                ChecksumSHA256=base64.b64encode(digest).decode("ascii"),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _ALREADY_THERE:
                raise WormAlreadyStoredError(f"{key} is already stored") from exc
            raise
        version_id = response.get("VersionId")
        if not version_id:
            raise WormError(f"the store gave no version for {key}: is versioning on?")
        if hashlib.sha256(self.get(key, version_id)).digest() != digest:
            raise WormIntegrityError(f"{key} reads back different from what was written")
        return StoredObject(key, str(version_id), digest.hex(), retain_until)

    def get(self, key: str, version_id: str | None = None) -> bytes:
        extra = {"VersionId": version_id} if version_id else {}
        response = self._client.get_object(Bucket=self._bucket, Key=key, **extra)
        body: bytes = response["Body"].read()
        return body

    def version_of(self, key: str) -> str:
        """Current version of ``key``: lets a retried write find what the first one stored."""
        response = self._client.head_object(Bucket=self._bucket, Key=key)
        return str(response["VersionId"])

    def retention(self, key: str, version_id: str) -> tuple[str, dt.datetime]:
        response = self._client.get_object_retention(
            Bucket=self._bucket, Key=key, VersionId=version_id
        )
        retention = response["Retention"]
        return str(retention["Mode"]), retention["RetainUntilDate"]


def _create_bucket(client: Any, bucket: str, locked: bool) -> None:
    try:
        client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=locked)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in _BUCKET_EXISTS:
            raise


def ensure_buckets(client: Any, default_retention_days: int) -> None:
    """Create both buckets if missing: ``evidence`` locked, ``working`` versioned."""
    if default_retention_days < 1:
        raise ValueError("the default retention is at least one day")
    _create_bucket(client, EVIDENCE_BUCKET, locked=True)
    client.put_object_lock_configuration(
        Bucket=EVIDENCE_BUCKET,
        ObjectLockConfiguration={
            "ObjectLockEnabled": "Enabled",
            "Rule": {"DefaultRetention": {"Mode": LOCK_MODE, "Days": default_retention_days}},
        },
    )
    _create_bucket(client, WORKING_BUCKET, locked=False)
    client.put_bucket_versioning(
        Bucket=WORKING_BUCKET, VersioningConfiguration={"Status": "Enabled"}
    )
