"""Contrato uniforme de salud (ARG-001)."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from argos_comun.salud import montar_salud


async def _ok() -> bool:
    return True


async def _no() -> bool:
    return False


async def _explota() -> bool:
    raise ConnectionError("sin base")


async def _lenta() -> bool:
    await asyncio.sleep(1)
    return True


def _cliente(**comprobaciones: object) -> TestClient:
    app = FastAPI()
    montar_salud(app, "svc", "1.2.3", comprobaciones, tiempo_max=0.2)  # type: ignore[arg-type]
    return TestClient(app)


def test_todo_bien_responde_200() -> None:
    r = _cliente(postgres=_ok, diario=_ok).get("/salud")
    assert r.status_code == 200
    assert r.json() == {
        "servicio": "svc",
        "version": "1.2.3",
        "estado": "ok",
        "comprobaciones": {"postgres": "ok", "diario": "ok"},
    }


def test_una_dependencia_caida_responde_503() -> None:
    r = _cliente(postgres=_ok, diario=_no).get("/salud")
    assert r.status_code == 503
    assert r.json()["estado"] == "degradado"
    assert r.json()["comprobaciones"]["diario"] == "fallo"


def test_una_excepcion_cuenta_como_fallo() -> None:
    assert _cliente(postgres=_explota).get("/salud").json()["comprobaciones"]["postgres"] == "fallo"


def test_una_comprobacion_lenta_cuenta_como_fallo() -> None:
    assert _cliente(nats=_lenta).get("/salud").json()["comprobaciones"]["nats"] == "fallo"


def test_viva_no_depende_de_nada() -> None:
    r = _cliente(postgres=_no).get("/salud/viva")
    assert r.status_code == 200 and r.json() == {"servicio": "svc", "estado": "vivo"}
