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
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError

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


def envelope(service: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if not _EVENT_TYPE.match(event_type):
        raise ValueError(f"invalid event type: {event_type!r} (expected domain.event.vN)")
    return {
        "specversion": "1.0",
        "id": str(uuid7()),
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


def bus_from_config(
    service: str, cfg: ArgosConfig, journal: PostgresJournal | None = None
) -> "Bus":
    """The bus of a service with the NATS identity of its configuration."""
    password = cfg.NATS_PASSWORD.get_secret_value() if cfg.NATS_PASSWORD else None
    tls = ReloadingTLS(server=False, cert_dir=cfg.TLS_DIR).context() if cfg.TLS_DIR else None
    return Bus(service, cfg.NATS_URL, journal, user=cfg.NATS_USER, password=password, tls=tls)


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
        tls: ssl.SSLContext | None = None,
    ) -> None:
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
        if self._tls is not None:
            options["tls"] = self._tls
        self._nc = await nats.connect(self._url, name=self.service, **options)
        self._js = self._nc.jetstream()

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc, self._js = None, None

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        if not _SUBJECT.match(subject):
            raise ValueError(f"invalid subject: {subject!r}")
        event = envelope(self.service, event_type, data)
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
        ack = await self.js.publish(subject, json.dumps(event, ensure_ascii=False).encode("utf-8"))
        return int(ack.seq)

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
            except Exception:
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
                deliver_policy=DeliverPolicy.ALL, max_deliver=self._max_deliveries, ack_wait=60
            ),
        )
