"""Uniform service health: /health/live (process) and /health (dependencies) (ARG-001)."""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

HealthCheck = Callable[[], Awaitable[bool]]


def mount_health(
    app: FastAPI,
    service: str,
    version: str,
    checks: dict[str, HealthCheck],
    timeout: float = 2.0,
) -> None:
    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"service": service, "status": "alive"}

    @app.get("/health")
    async def health() -> JSONResponse:
        results: dict[str, str] = {}
        for name, check in checks.items():
            try:
                ok = await asyncio.wait_for(check(), timeout=timeout)
            except Exception:  # a failing dependency must not take the endpoint down with it
                ok = False
            results[name] = "ok" if ok else "fail"
        status = "ok" if all(v == "ok" for v in results.values()) else "degraded"
        return JSONResponse(
            status_code=200 if status == "ok" else 503,
            content={
                "service": service,
                "version": version,
                "status": status,
                "checks": results,
            },
        )
