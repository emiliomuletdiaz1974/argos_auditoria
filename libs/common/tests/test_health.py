"""Uniform health contract (ARG-001)."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from argos_common.health import mount_health


async def _ok() -> bool:
    return True


async def _down() -> bool:
    return False


async def _raises() -> bool:
    raise ConnectionError("no database")


async def _slow() -> bool:
    await asyncio.sleep(1)
    return True


def _client(**checks: object) -> TestClient:
    app = FastAPI()
    mount_health(app, "svc", "1.2.3", checks, timeout=0.2)  # type: ignore[arg-type]
    return TestClient(app)


def test_all_healthy_returns_200() -> None:
    r = _client(postgres=_ok, journal=_ok).get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "service": "svc",
        "version": "1.2.3",
        "status": "ok",
        "checks": {"postgres": "ok", "journal": "ok"},
    }


def test_one_failing_dependency_returns_503() -> None:
    r = _client(postgres=_ok, journal=_down).get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["journal"] == "fail"


def test_an_exception_counts_as_failure() -> None:
    assert _client(postgres=_raises).get("/health").json()["checks"]["postgres"] == "fail"


def test_a_slow_check_counts_as_failure() -> None:
    assert _client(nats=_slow).get("/health").json()["checks"]["nats"] == "fail"


def test_live_depends_on_nothing() -> None:
    r = _client(postgres=_down).get("/health/live")
    assert r.status_code == 200 and r.json() == {"service": "svc", "status": "alive"}
