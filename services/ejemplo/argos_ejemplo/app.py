"""Servicio de ejemplo de la Fase 1: arranca con la librería común, escribe y verifica el diario."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any

import psycopg
from fastapi import FastAPI, Query

from argos_comun.config import get_config
from argos_comun.diario_pg import DiarioPostgres
from argos_comun.logs import configurar_logging, get_logger
from argos_comun.salud import montar_salud

SERVICIO = "argos-ejemplo"


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    cfg = get_config()  # con configuración inválida, el servicio no llega a arrancar
    configurar_logging(SERVICIO, cfg.LOG_LEVEL)
    log = get_logger(__name__, "ARG-001")
    log.info("servicio arrancado")
    yield
    log.info("parada limpia")


app = FastAPI(title=SERVICIO, lifespan=ciclo_de_vida)


def _diario() -> DiarioPostgres:
    return DiarioPostgres(get_config().DATABASE_URL)


async def _postgres_ok() -> bool:
    def consultar() -> bool:
        with psycopg.connect(get_config().DATABASE_URL, connect_timeout=2) as conn:
            return conn.execute("SELECT 1").fetchone() == (1,)

    return await asyncio.to_thread(consultar)


async def _diario_ok() -> bool:
    return await asyncio.to_thread(lambda: _diario().verificar().integro)


montar_salud(
    app, SERVICIO, version("argos-ejemplo"), {"postgres": _postgres_ok, "diario": _diario_ok}
)


@app.post("/demo/asientos")
async def escribir_asientos(n: int = Query(default=100, ge=1, le=1000)) -> dict[str, int]:
    def escribir() -> int:
        diario, ultimo = _diario(), 0
        for i in range(n):
            ultimo = diario.registrar(f"system:{SERVICIO}", "demo.asiento", {"i": i})
        return ultimo

    ultimo = await asyncio.to_thread(escribir)
    get_logger(__name__, "ARG-005").info("asientos escritos", extra={"journal_seq": ultimo})
    return {"escritos": n, "ultimo_seq": ultimo}


@app.get("/diario/verificacion")
async def verificar_diario() -> dict[str, Any]:
    r = await asyncio.to_thread(lambda: _diario().verificar())
    return {
        "integro": r.integro,
        "verificados": r.verificados,
        "cabeza_seq": r.cabeza_seq,
        "anomalias": [{"seq": a.seq, "motivo": a.motivo} for a in r.anomalias[:20]],
    }
