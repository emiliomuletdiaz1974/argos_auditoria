"""The domain health service: `/metrics` for Prometheus and `/facts` for the self-check (ARG-094).

Every check runs on its own cadence: the journal tail every 5 minutes and the whole journal once a
day, the WORM canary and the domain counts every 30 seconds, the certificates every hour. After
each round the facts only this service observes are recorded in `argos.health_facts`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any

import boto3
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from argos_common.capacity import limits_of
from argos_common.config import ArgosConfig, get_config
from argos_common.dynamic_db import start_from_config
from argos_common.health import mount_health
from argos_common.logs import configure_logging, get_logger
from argos_common.vault_auth import database_login
from argos_evidence.worm import WormStore

from .measures import render_metrics
from .monitor import Monitor, vault_certificates

SERVICE_NAME = "argos-health"


class HealthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGOS_HEALTH_", extra="ignore")

    S3_ENDPOINT: str | None = None
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = SecretStr("")
    PKI_URL: str | None = None
    EVIDENCE_PATH: Path | None = None
    # K-99: when the volume cannot be mounted here, the address where the store publishes its usage.
    EVIDENCE_USAGE_URL: str | None = None
    JOURNAL_TAIL: int = 10_000
    JOURNAL_TAIL_SECONDS: int = 300
    JOURNAL_FULL_SECONDS: int = 86_400
    CANARY_SECONDS: int = 30
    DOMAIN_SECONDS: int = 30
    CERTIFICATES_SECONDS: int = 3_600
    CAPACITY_SECONDS: int = 86_400
    # The services the certificate issuer renews (its ARGOS_TLS_SERVICES), `folder=cn,alt;…`:
    # only their certificates count, and one of them without a certificate counts (QA-088).
    TLS_SERVICES: str = ""
    VERSION_FILE: Path = Path("VERSION")  # the release, copied into the image beside the code


def build_monitor(dsn: str, settings: HealthSettings, config: ArgosConfig | None = None) -> Monitor:
    store = None
    if settings.S3_ENDPOINT:
        client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY.get_secret_value(),
            region_name="us-east-1",
        )
        store = WormStore(client)
    certificates = None
    if settings.PKI_URL:
        token = database_login(config) if config is not None else None
        certificates = vault_certificates(settings.PKI_URL, token)
    release = (
        settings.VERSION_FILE.read_text(encoding="utf-8").strip()
        if settings.VERSION_FILE.is_file()
        else "unknown"
    )
    size = None
    if config is not None and config.SIZE and config.SIZES_FILE:
        size = (config.SIZE, limits_of(Path(config.SIZES_FILE), config.SIZE))
    expected = frozenset(
        names.split("=", 1)[1].split(",")[0]
        for names in settings.TLS_SERVICES.split(";")
        if "=" in names
    )
    return Monitor(
        dsn,
        store,
        certificates,
        settings.EVIDENCE_PATH,
        settings.JOURNAL_TAIL,
        release=release,
        size=size,
        expected_certificates=expected or None,
        evidence_usage_url=settings.EVIDENCE_USAGE_URL,
    )


async def _every(seconds: int, check: Callable[[], None], monitor: Monitor) -> None:
    log = get_logger(__name__, "ARG-094")
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(check)
            await asyncio.to_thread(monitor.publish)
        except Exception as exc:  # one failed round never stops the service
            log.warning("health round failed", extra={"error": str(exc)[:200]})


def create_app(monitor: Monitor | None = None, settings: HealthSettings | None = None) -> FastAPI:
    state: dict[str, Monitor] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task[None]] = []
        if monitor is not None:
            state["monitor"] = monitor
        else:
            cfg = get_config()
            configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)
            start_from_config(cfg)  # F09-05: the dynamic credential, before any connection
            chosen = settings or HealthSettings()
            current = build_monitor(cfg.DATABASE_URL, chosen, cfg)
            state["monitor"] = current
            await asyncio.to_thread(current.run_all)
            await asyncio.to_thread(current.publish)
            cadence = [
                (chosen.JOURNAL_TAIL_SECONDS, current.check_journal),
                (chosen.JOURNAL_TAIL_SECONDS, current.check_security_log),
                (chosen.JOURNAL_FULL_SECONDS, lambda: current.check_journal(full=True)),
                (chosen.CANARY_SECONDS, current.check_worm),
                (chosen.DOMAIN_SECONDS, current.check_domain),
                (chosen.CERTIFICATES_SECONDS, current.check_certificates),
                (chosen.DOMAIN_SECONDS, current.check_volume),
                (chosen.CAPACITY_SECONDS, current.check_capacity),
            ]
            tasks = [asyncio.create_task(_every(s, c, current)) for s, c in cadence]
            get_logger(__name__, "ARG-094").info("health service started")
        yield
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title=SERVICE_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            render_metrics(state["monitor"].observations()),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/facts")
    def facts() -> dict[str, Any]:
        current = state["monitor"]
        single = {o.name: o.value for o in current.observations() if not o.labels}
        return {"facts": current.facts(), "measures": single}

    async def _alive() -> bool:
        return "monitor" in state

    mount_health(app, SERVICE_NAME, version("argos-health"), {"monitor": _alive})
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000, timeout_graceful_shutdown=10)  # noqa: S104


if __name__ == "__main__":
    main()
