"""Delivering a webhook: sign, send, record the attempt, and let Temporal retry (ARG-079).

Each attempt leaves its trace in the inbox before anything else happens, so a crash between two
attempts does not erase what was tried. A failed attempt raises while there are attempts left, and
the retry policy of the workflow spaces them out exponentially; the last one records `failed`.
"""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import psycopg
from temporalio import activity

from argos_api.webhooks.destination import (
    DestinationRefusedError,
    Resolver,
    check_destination,
    resolve_host,
)
from argos_api.webhooks.signing import EVENT_HEADER, SIGNATURE_HEADER, sign
from argos_api.webhooks.store import SecretWriter
from argos_api.webhooks.templates import render
from argos_api.webhooks.workflow import MAX_ATTEMPTS, TIMEOUT_SECONDS

DELIVERED = "delivered"
FAILED = "failed"
RETRYING = "retrying"
# What the inbox says about a failure: its kind, never the text of the other side, which can carry
# internal names, addresses or whatever the destination chose to answer (SEC-031).
ERROR_KINDS = ("destination_refused", "timeout", "connection", "transport")


def error_kind(exc: Exception) -> str:
    if isinstance(exc, DestinationRefusedError):
        return "destination_refused"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection"
    return "transport"


class DeliveryFailedError(Exception):
    """This attempt did not arrive; Temporal will try again while there are attempts left."""


def _load(dsn: str, delivery_id: str) -> tuple[str, str, str, dict[str, Any], int]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT w.url, w.secret_ref, w.template, d.event, d.attempts"
            " FROM argos.webhook_deliveries d JOIN argos.webhooks w ON w.id = d.webhook_id"
            " WHERE d.id = %s",
            (delivery_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"no delivery {delivery_id}")
    return str(row[0]), str(row[1]), str(row[2]), dict(row[3]), int(row[4])


def _record(
    dsn: str, delivery_id: str, attempts: int, status: str, code: int | None, error: str | None
) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.webhook_deliveries SET attempts = %s, status = %s,"
            " last_status_code = %s, last_error = %s, last_at = now(),"
            " delivered_at = CASE WHEN %s = 'delivered' THEN now() ELSE delivered_at END"
            " WHERE id = %s",
            (attempts, status, code, error, status, delivery_id),
        )


class WebhookActivities:
    def __init__(
        self,
        dsn: str,
        secrets: SecretWriter,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        allowed: tuple[str, ...] = (),
        resolve: Resolver = resolve_host,
    ) -> None:
        self._dsn = dsn
        self._secrets = secrets
        self._transport = transport
        self._clock = clock
        self._allowed = allowed
        self._resolve = resolve

    def deliver_now(self, delivery_id: str, max_attempts: int = MAX_ATTEMPTS) -> str:
        url, secret_ref, template, event, attempts = _load(self._dsn, delivery_id)
        try:
            # Checked again before each delivery: a name may resolve elsewhere by now (SEC-031).
            check_destination(url, resolve=self._resolve, allowed=self._allowed)
        except DestinationRefusedError as refused:
            _record(self._dsn, delivery_id, attempts + 1, FAILED, None, error_kind(refused))
            return FAILED
        body = json.dumps(render(template, event), ensure_ascii=False).encode()
        secret = self._secrets.read(secret_ref)["secret"]
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(secret, int(self._clock()), body),
            EVENT_HEADER: str(event.get("type", "")),
        }
        code: int | None = None
        error: str | None = None
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
                code = client.post(url, content=body, headers=headers).status_code
        except httpx.HTTPError as exc:
            error = error_kind(exc)
        attempts += 1
        arrived = code is not None and code < 300
        if arrived:
            _record(self._dsn, delivery_id, attempts, DELIVERED, code, None)
            return DELIVERED
        if attempts >= max_attempts:
            _record(self._dsn, delivery_id, attempts, FAILED, code, error)
            return FAILED
        _record(self._dsn, delivery_id, attempts, RETRYING, code, error)
        raise DeliveryFailedError(f"attempt {attempts} did not arrive: {code or error}")

    @property
    def allowed(self) -> tuple[str, ...]:
        return self._allowed

    @activity.defn(name="deliver_webhook")
    async def deliver(self, delivery_id: str, max_attempts: int) -> str:
        return await asyncio.to_thread(self.deliver_now, delivery_id, max_attempts)

    def all(self) -> list[Any]:
        return [self.deliver]
