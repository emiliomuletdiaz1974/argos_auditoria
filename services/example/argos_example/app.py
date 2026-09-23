"""Phase 1 example service: starts with the common library, writes and verifies the journal."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any

import psycopg
from fastapi import FastAPI, Query

from argos_common.config import get_config
from argos_common.dynamic_db import start_from_config
from argos_common.health import mount_health
from argos_common.journal_pg import PostgresJournal
from argos_common.logs import configure_logging, get_logger

SERVICE_NAME = "argos-example"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    cfg = get_config()  # with an invalid configuration the service never finishes starting
    configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)
    start_from_config(cfg)  # F09-05: the dynamic credential, before any connection
    log = get_logger(__name__, "ARG-001")
    log.info("service started")
    yield
    log.info("clean shutdown")


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


def _journal() -> PostgresJournal:
    return PostgresJournal(get_config().DATABASE_URL)


async def _postgres_ok() -> bool:
    def query() -> bool:
        with psycopg.connect(get_config().DATABASE_URL, connect_timeout=2) as conn:
            return conn.execute("SELECT 1").fetchone() == (1,)

    return await asyncio.to_thread(query)


async def _journal_ok() -> bool:
    return await asyncio.to_thread(lambda: _journal().verify().intact)


mount_health(
    app, SERVICE_NAME, version("argos-example"), {"postgres": _postgres_ok, "journal": _journal_ok}
)


@app.post("/demo/entries")
async def write_entries(n: int = Query(default=100, ge=1, le=1000)) -> dict[str, int]:
    def write() -> int:
        journal, last = _journal(), 0
        for i in range(n):
            last = journal.append(f"system:{SERVICE_NAME}", "demo.entry", {"i": i})
        return last

    last = await asyncio.to_thread(write)
    get_logger(__name__, "ARG-005").info("entries written", extra={"journal_seq": last})
    return {"written": n, "last_seq": last}


@app.get("/journal/verification")
async def verify_journal() -> dict[str, Any]:
    r = await asyncio.to_thread(lambda: _journal().verify())
    return {
        "intact": r.intact,
        "verified": r.verified,
        "head_seq": r.head_seq,
        "anomalies": [{"seq": a.seq, "reason": a.reason} for a in r.anomalies[:20]],
    }
