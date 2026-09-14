"""Salud uniforme de los servicios: /salud/viva (proceso) y /salud (dependencias) (ARG-001)."""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

Comprobacion = Callable[[], Awaitable[bool]]


def montar_salud(
    app: FastAPI,
    servicio: str,
    version: str,
    comprobaciones: dict[str, Comprobacion],
    tiempo_max: float = 2.0,
) -> None:
    @app.get("/salud/viva")
    async def salud_viva() -> dict[str, str]:
        return {"servicio": servicio, "estado": "vivo"}

    @app.get("/salud")
    async def salud() -> JSONResponse:
        resultados: dict[str, str] = {}
        for nombre, comprobar in comprobaciones.items():
            try:
                ok = await asyncio.wait_for(comprobar(), timeout=tiempo_max)
            except Exception:  # una dependencia caída no debe tumbar el propio endpoint
                ok = False
            resultados[nombre] = "ok" if ok else "fallo"
        estado = "ok" if all(v == "ok" for v in resultados.values()) else "degradado"
        return JSONResponse(
            status_code=200 if estado == "ok" else 503,
            content={
                "servicio": servicio,
                "version": version,
                "estado": estado,
                "comprobaciones": resultados,
            },
        )
