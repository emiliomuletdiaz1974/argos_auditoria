"""argos_events: CloudEvents 1.0 publishing and consumption over NATS JetStream (ARG-006).

Every service uses this library; nobody talks to NATS directly.

Since F09-06 (ARG-083, security review SEC-026) a service connects with its client certificate and
does not create or change streams: the streams are the platform's, created once by
`tools/nats_streams.py` with its own user (`ensure_streams`).
"""

import asyncio
import json
import os
import re
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import nats
import psycopg
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError
from psycopg.types.json import Jsonb

from argos_common.config import ArgosConfig
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_common.logs import get_logger
from argos_tls import ReloadingTLS

_DAY = 86400
STREAMS: tuple[StreamConfig, ...] = (
    StreamConfig(
        name="DISCOVERY",
        subjects=["argos.discovery.>"],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_age=30 * _DAY,
        num_replicas=1,
    ),
    StreamConfig(
        name="CHALLENGE",
        subjects=["argos.challenge.>", "argos.campaign.>"],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_age=90 * _DAY,
        num_replicas=1,
    ),
    StreamConfig(
        name="EVIDENCE",
        subjects=["argos.evidence.>"],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        max_bytes=50 * 1024**3,
        num_replicas=1,
    ),
)
_SUBJECT = re.compile(r"^argos\.(discovery|challenge|campaign|evidence)(\.[a-z0-9_]+)+$")
_EVENT_TYPE = re.compile(r"^[a-z_]+(\.[a-z_]+)+\.v\d+$")
_log = get_logger("argos_events", "ARG-006")

Handler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]


DeadLetter = Callable[[dict[str, Any]], None]


def envelope(
    service: str, event_type: str, data: dict[str, Any], event_id: str | None = None
) -> dict[str, Any]:
    if not _EVENT_TYPE.match(event_type):
        raise ValueError(f"invalid event type: {event_type!r} (expected domain.event.vN)")
    return {
        "specversion": "1.0",
        "id": event_id or str(uuid7()),
        "source": f"//argos/{service}",
        "type": f"eu.argos.{event_type}",
        "time": datetime.now(UTC).isoformat(),
        "datacontenttype": "application/json",
        "data": data,
    }


async def ensure_streams(js: JetStreamContext) -> None:
    for cfg in STREAMS:
        try:
            await js.stream_info(str(cfg.name))
        except NotFoundError:
            await js.add_stream(cfg)
        else:
            await js.update_stream(cfg)


def postgres_dead_letter(dsn: str, service: str) -> DeadLetter:
    """Keep an event whose deliveries ran out in `argos.event_dead_letters`, where the health
    service counts it and `EventsDeadLettered` makes it seen (QA-001)."""

    def keep(letter: dict[str, Any]) -> None:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO argos.event_dead_letters"
                " (service, subject, durable, event_id, event, error, deliveries)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    service,
                    letter["subject"],
                    letter["durable"],
                    str(letter["event"].get("id", "")),
                    Jsonb(letter["event"]),
                    letter["error"][:2000],
                    letter["deliveries"],
                ),
            )

    return keep


def bus_from_config(
    service: str, cfg: ArgosConfig, journal: PostgresJournal | None = None
) -> "Bus":
    """The bus of a service with the NATS identity of its configuration; its certificate is
    renewed on reconnection, and what it cannot deliver is kept as a dead letter."""
    password = cfg.NATS_PASSWORD.get_secret_value() if cfg.NATS_PASSWORD else None
    tls = ReloadingTLS(server=False, cert_dir=cfg.TLS_DIR) if cfg.TLS_DIR else None
    dead_letter = postgres_dead_letter(cfg.DATABASE_URL, service) if cfg.DATABASE_URL else None
    return Bus(
        service,
        cfg.NATS_URL,
        journal,
        user=cfg.NATS_USER,
        password=password,
        tls=tls,
        dead_letter=dead_letter,
    )


def tls_from_environment() -> ssl.SSLContext | None:
    """The client certificate of this process, when ARGOS_TLS_DIR names one (tests, tools)."""
    folder = os.environ.get("ARGOS_TLS_DIR")
    return ReloadingTLS(server=False, cert_dir=folder).context() if folder else None


class Bus:
    def __init__(
        self,
        service: str,
        url: str,
        journal: PostgresJournal | None = None,
        retry_delay: float = 30.0,
        max_deliveries: int = 5,
        *,
        user: str | None = None,
        password: str | None = None,
        tls: ssl.SSLContext | ReloadingTLS | None = None,
        dead_letter: DeadLetter | None = None,
    ) -> None:
        self._dead_letter = dead_letter
        self.service = service
        self._url = url
        self._journal = journal
        self._retry_delay = retry_delay
        self._max_deliveries = max_deliveries
        # The server's permissions for this user decide which subjects the service may publish.
        self._credentials = {"user": user, "password": password} if user else {}
        self._tls = tls if tls is not None else tls_from_environment()
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None

    def __repr__(self) -> str:
        return f"Bus(service={self.service!r}, url={self._url!r})"

    @property
    def js(self) -> JetStreamContext:
        if self._js is None:
            raise RuntimeError("Bus is not connected: call connect() first")
        return self._js

    async def connect(self) -> None:
        options: dict[str, Any] = dict(self._credentials)
        tls = self._tls
        if isinstance(tls, ssl.SSLContext):
            options["tls"] = tls
        elif tls is not None:
            options["tls"] = tls.client_context()

            async def renew_certificate() -> None:  # before reconnecting (QA-004)
                await asyncio.to_thread(tls.refresh)

            options["disconnected_cb"] = renew_certificate
        self._nc = await nats.connect(self._url, name=self.service, **options)
        self._js = self._nc.jetstream()

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc, self._js = None, None

    async def publish(
        self,
        subject: str,
        event_type: str,
        data: dict[str, Any],
        audit: bool = False,
        event_id: str | None = None,
    ) -> int:
        if not _SUBJECT.match(subject):
            raise ValueError(f"invalid subject: {subject!r}")
        event = envelope(self.service, event_type, data, event_id)
        # Serialised first: nothing is journaled for an event that could never leave (QA-005).
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        if audit:
            if self._journal is None:
                raise ValueError("audit=True requires a journal")
            # record first: the entry exists even if publishing fails afterwards
            await asyncio.to_thread(
                self._journal.append,
                f"system:{self.service}",
                "event.publish",
                {"id": event["id"], "subject": subject, "type": event["type"]},
            )
        # JetStream drops a second message with the same id within its duplicate window: a
        # caller that retries with the same `event_id` publishes once (QA-005).
        ack = await self.js.publish(subject, payload, headers={"Nats-Msg-Id": event["id"]})
        return int(ack.seq)

    async def _keep_dead_letter(
        self,
        subject: str,
        durable: str,
        event: dict[str, Any],
        failure: Exception,
        deliveries: int,
    ) -> bool:
        """True when the event was kept; False leaves it to be delivered again."""
        if self._dead_letter is None:
            _log.error(
                "event delivery exhausted and no dead letter store: it is delivered again",
                extra={"trace_id": event.get("id")},
            )
            return False
        letter = {
            "subject": subject,
            "durable": durable,
            "event": event,
            "error": f"{type(failure).__name__}: {failure}",
            "deliveries": deliveries,
        }
        try:
            await asyncio.to_thread(self._dead_letter, letter)
        except Exception:
            _log.exception("dead letter not kept; the event is delivered again")
            return False
        _log.error(
            "event delivery exhausted; kept as a dead letter", extra={"trace_id": event.get("id")}
        )
        return True

    async def subscribe(self, subject: str, durable: str, handler: Handler) -> None:
        async def _on_message(msg: Msg) -> None:
            try:
                event = json.loads(msg.data)
                data = event["data"]
            except (ValueError, KeyError, TypeError):
                _log.warning("malformed event discarded", extra={"trace_id": msg.subject})
                await msg.term()
                return
            try:
                await handler(data, event)
            except Exception as failure:
                deliveries = int(getattr(getattr(msg, "metadata", None), "num_delivered", 0) or 0)
                if deliveries >= self._max_deliveries and await self._keep_dead_letter(
                    msg.subject, durable, event, failure, deliveries
                ):
                    await msg.term()
                    return
                _log.exception(
                    "handler failed; message will be redelivered",
                    extra={"trace_id": event.get("id")},
                )
                await msg.nak(delay=self._retry_delay)
                return
            await msg.ack()

        await self.js.subscribe(
            subject,
            durable=durable,
            cb=_on_message,
            manual_ack=True,
            config=ConsumerConfig(
                # Unlimited for JetStream: the bus counts, and at the limit hands the event to
                # the dead letters; if it cannot, the event keeps coming back (QA-001).
                deliver_policy=DeliverPolicy.ALL,
                max_deliver=-1,
                ack_wait=60,
            ),
        )
