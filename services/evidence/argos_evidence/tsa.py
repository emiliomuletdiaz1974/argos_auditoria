"""RFC 3161 time stamps with a persistent queue (ARG-065, deviation note ARG-064-065).

The signature proves who; the time stamp proves when, and an authority alien to
maker and client says it. The appliance may be isolated (P-02), so stamping is
asynchronous by design: an object is queued the moment it is signed and stays
visibly "queued" until a verified token exists for it.

Two ways to get the token, one verifier. Online, ``process_queue`` asks the TSA
through a transport. Isolated, ``export_requests`` hands out the queries and
``import_replies`` takes back what was stamped elsewhere. Every reply goes
through ``verify_reply``: status, chain to a trusted root, nonce, TSA
certificate and the SHA-256 of the exact bytes stored in the WORM.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg
from cryptography import x509
from rfc3161_client import (
    HashAlgorithm,
    TimeStampRequest,
    TimestampRequestBuilder,
)

from argos_evidence.core.integrity import file_digest
from argos_evidence.core.timestamp import TimestampRejectedError, verify_reply
from argos_evidence.worm import WormAlreadyStoredError, WormStore

Transport = Callable[[bytes], bytes]
QUERY_TYPE = "application/timestamp-query"
REPLY_TYPE = "application/timestamp-reply"


@dataclass(frozen=True)
class Stamp:
    object_key: str
    status: str
    attempts: int
    last_error: str | None
    token_key: str | None
    token_version_id: str | None
    gen_time: dt.datetime | None
    policy: str | None


@dataclass
class QueueSummary:
    stamped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def new_request(data: bytes) -> TimeStampRequest:
    """A query over the SHA-256 of ``data``, with a fresh nonce and asking for the certificate."""
    return (
        TimestampRequestBuilder()
        .data(data)
        .hash_algorithm(HashAlgorithm.SHA256)
        .nonce(nonce=True)
        .cert_request(cert_request=True)
        .build()
    )


def http_transport(url: str, timeout: float = 10.0) -> Transport:
    def send(query: bytes) -> bytes:
        response = httpx.post(
            url, content=query, headers={"Content-Type": QUERY_TYPE}, timeout=timeout
        )
        response.raise_for_status()
        if response.headers.get("Content-Type", "").split(";")[0] != REPLY_TYPE:
            raise httpx.HTTPError(f"the TSA answered {response.headers.get('Content-Type')}")
        return response.content

    return send


def enqueue(
    dsn: str,
    object_key: str,
    version_id: str,
    sha256: str,
    conn: psycopg.Connection[Any] | None = None,
) -> None:
    """Queue an object for stamping; queuing it again changes nothing."""
    statement = (
        "INSERT INTO argos.tsa_queue (object_key, version_id, sha256) VALUES (%s, %s, %s)"
        " ON CONFLICT (object_key) DO NOTHING"
    )
    if conn is not None:
        conn.execute(statement, (object_key, version_id, sha256))
        return
    with psycopg.connect(dsn) as own:
        own.execute(statement, (object_key, version_id, sha256))


_STAMP_COLUMNS = (
    "object_key, status, attempts, last_error, token_key, token_version_id, gen_time, policy"
)


def stamp_of(dsn: str, object_key: str) -> Stamp | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            f"SELECT {_STAMP_COLUMNS} FROM argos.tsa_queue WHERE object_key = %s",  # noqa: S608
            (object_key,),
        ).fetchone()
    return None if row is None else Stamp(*row)


def _queued(dsn: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT object_key, version_id, sha256 FROM argos.tsa_queue"
            " WHERE status = 'queued' ORDER BY enqueued_at, object_key"
        ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def _stored_object(store: WormStore, key: str, version_id: str, sha256: str) -> bytes:
    data = store.get(key, version_id)
    if file_digest(data) != sha256:
        raise TimestampRejectedError(f"{key} in the WORM store is not the object that was queued")
    return data


def _request_for(dsn: str, object_key: str, data: bytes) -> bytes:
    """A new query for the object; its nonce replaces any earlier one."""
    request = new_request(data)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.tsa_queue SET nonce = %s, requested_at = now()"
            " WHERE object_key = %s AND status = 'queued'",
            (request.nonce, object_key),
        )
    return request.as_bytes()


def _record_failure(dsn: str, object_key: str, error: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.tsa_queue SET attempts = attempts + 1, last_error = %s"
            " WHERE object_key = %s AND status = 'queued'",
            (error[:500], object_key),
        )


def accept_reply(
    dsn: str,
    store: WormStore,
    object_key: str,
    reply: bytes,
    roots: list[x509.Certificate],
    retain_until: dt.datetime,
) -> Stamp:
    """Verify a reply against the queued object and its last request, then keep the token."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT version_id, sha256, nonce, status FROM argos.tsa_queue WHERE object_key = %s",
            (object_key,),
        ).fetchone()
    if row is None:
        raise TimestampRejectedError(f"{object_key} is not queued for a time stamp")
    version_id, sha256, nonce, status = str(row[0]), str(row[1]), row[2], str(row[3])
    if status != "queued":
        raise TimestampRejectedError(f"{object_key} is already {status}")
    if nonce is None:
        raise TimestampRejectedError(f"no request was made for {object_key}")

    data = _stored_object(store, object_key, version_id, sha256)
    response = verify_reply(reply, data, int(nonce), roots)

    token_key = f"{object_key}.tsr"
    try:
        token_version = store.put_immutable(token_key, reply, retain_until).version_id
    except WormAlreadyStoredError:
        token_version = store.version_of(token_key)
        if store.get(token_key, token_version) != reply:
            raise TimestampRejectedError(f"{token_key} already holds another token") from None

    info = response.tst_info
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.tsa_queue SET status = 'stamped', token_key = %s,"
            " token_version_id = %s, gen_time = %s, policy = %s, stamped_at = now()"
            " WHERE object_key = %s AND status = 'queued'",
            (token_key, token_version, info.gen_time, info.policy.dotted_string, object_key),
        )
    stamp = stamp_of(dsn, object_key)
    if stamp is None or stamp.status != "stamped":  # pragma: no cover - only under a race
        raise TimestampRejectedError(f"{object_key} could not be marked as stamped")
    return stamp


def process_queue(
    dsn: str,
    store: WormStore,
    transport: Transport,
    roots: list[x509.Certificate],
    retain_until: dt.datetime,
) -> QueueSummary:
    """Try every queued object once. A failure is recorded and the object stays queued."""
    summary = QueueSummary()
    for object_key, version_id, sha256 in _queued(dsn):
        try:
            data = _stored_object(store, object_key, version_id, sha256)
            reply = transport(_request_for(dsn, object_key, data))
            accept_reply(dsn, store, object_key, reply, roots, retain_until)
        except (httpx.HTTPError, TimestampRejectedError) as exc:
            _record_failure(dsn, object_key, f"{type(exc).__name__}: {exc}")
            summary.failed.append(object_key)
        else:
            summary.stamped.append(object_key)
    return summary


def export_requests(dsn: str, store: WormStore) -> dict[str, bytes]:
    """Isolated mode: one query per queued object, to be stamped outside the appliance."""
    requests: dict[str, bytes] = {}
    for object_key, version_id, sha256 in _queued(dsn):
        data = _stored_object(store, object_key, version_id, sha256)
        requests[object_key] = _request_for(dsn, object_key, data)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.tsa_queue SET exported_at = now() WHERE object_key = ANY(%s)",
            (list(requests),),
        )
    return requests


def import_replies(
    dsn: str,
    store: WormStore,
    replies: Mapping[str, bytes],
    roots: list[x509.Certificate],
    retain_until: dt.datetime,
) -> dict[str, TimestampRejectedError | None]:
    """Isolated mode: accept the replies brought back; ``None`` means stamped."""
    results: dict[str, TimestampRejectedError | None] = {}
    for object_key, reply in replies.items():
        try:
            accept_reply(dsn, store, object_key, reply, roots, retain_until)
        except TimestampRejectedError as exc:
            _record_failure(dsn, object_key, str(exc))
            results[object_key] = exc
        else:
            results[object_key] = None
    return results
