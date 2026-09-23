"""Subscriptions and the inbox of deliveries (ARG-079).

The secret of a subscription goes to the secret store the moment it arrives and is never read back
here: only the dispatcher reads it, to sign. What the database keeps is the path to it.
"""

from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal

VAULT_FOLDER = "webhooks"  # the path under the secret store, never the secret
_ERROR_KINDS = ("destination_refused", "timeout", "connection", "transport")
EVENT_TYPES = ("finding_opened", "campaign_sealed", "approval_requested")


class SecretWriter(Protocol):
    def read(self, path: str) -> dict[str, str]: ...

    def write(self, path: str, data: dict[str, str]) -> None: ...


def secret_path(webhook_id: str) -> str:
    return f"{VAULT_FOLDER}/{webhook_id}"


def create_webhook(
    dsn: str,
    secrets: SecretWriter,
    *,
    url: str,
    events: list[str],
    template: str,
    secret: str,
    created_by: str,
) -> dict[str, Any]:
    webhook_id = str(uuid7())
    path = secret_path(webhook_id)
    secrets.write(path, {"secret": secret})  # first the secret, then the row that points to it
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "INSERT INTO argos.webhooks (id, url, events, template, secret_ref, created_by)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING created_at",
            (webhook_id, url, events, template, path, created_by),
        ).fetchone()
        PostgresJournal(dsn).append(
            created_by,
            "webhook.subscribe",
            {"webhook": webhook_id, "url": url, "events": events, "template": template},
            conn=conn,
        )
    created_at = row[0].isoformat() if row else None
    return {
        "id": webhook_id,
        "url": url,
        "events": events,
        "template": template,
        "active": True,
        "created_by": created_by,
        "created_at": created_at,
    }


def list_webhooks(
    dsn: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    at, ident = after if after else (None, None)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id::text, url, events, template, active, created_by, created_at"
            " FROM argos.webhooks"
            " WHERE (%(at)s::timestamptz IS NULL OR (created_at, id::text) < (%(at)s, %(id)s))"
            " ORDER BY created_at DESC, id DESC LIMIT %(limit)s",
            {"at": at, "id": ident, "limit": limit},
        ).fetchall()
    return [
        {
            "id": row[0],
            "url": row[1],
            "events": list(row[2]),
            "template": row[3],
            "active": row[4],
            "created_by": row[5],
            "created_at": row[6].isoformat(),
        }
        for row in rows
    ]


def webhook_exists(dsn: str, webhook_id: str) -> bool:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT 1 FROM argos.webhooks WHERE id = %s", (webhook_id,)).fetchone()
    return row is not None


def list_deliveries(
    dsn: str, webhook_id: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    at, ident = after if after else (None, None)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id::text, event_type, status, attempts, last_status_code, last_error, last_at,"
            " delivered_at, created_at FROM argos.webhook_deliveries WHERE webhook_id = %(hook)s"
            " AND (%(at)s::timestamptz IS NULL OR (created_at, id::text) < (%(at)s, %(id)s))"
            " ORDER BY created_at DESC, id DESC LIMIT %(limit)s",
            {"hook": webhook_id, "at": at, "id": ident, "limit": limit},
        ).fetchall()
    return [
        {
            "id": row[0],
            "event_type": row[1],
            "status": row[2],
            "attempts": row[3],
            "last_status_code": row[4],
            # Rows written before the error kinds existed may hold raw text: never shown.
            "last_error": row[5] if row[5] in _ERROR_KINDS or row[5] is None else "transport",
            "last_at": row[6].isoformat() if row[6] else None,
            "delivered_at": row[7].isoformat() if row[7] else None,
            "created_at": row[8].isoformat(),
        }
        for row in rows
    ]


def enqueue_event(dsn: str, event_type: str, data: dict[str, Any]) -> list[str]:
    """One pending delivery per active subscription to `event_type`; returns their ids."""
    event = {"type": event_type, **data}
    with psycopg.connect(dsn) as conn:
        hooks = conn.execute(
            "SELECT id::text FROM argos.webhooks WHERE active AND %s = ANY(events) ORDER BY id",
            (event_type,),
        ).fetchall()
        created: list[str] = []
        for (webhook_id,) in hooks:
            delivery_id = str(uuid7())
            conn.execute(
                "INSERT INTO argos.webhook_deliveries (id, webhook_id, event_type, event)"
                " VALUES (%s, %s, %s, %s)",
                (delivery_id, webhook_id, event_type, Jsonb(event)),
            )
            created.append(delivery_id)
    return created
