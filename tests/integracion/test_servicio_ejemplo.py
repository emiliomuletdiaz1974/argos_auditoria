"""Servicio de ejemplo en proceso contra una base migrada."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argos_comun.config import get_config
from argos_comun.errors import ConfiguracionError

pytestmark = pytest.mark.integracion


@pytest.fixture
def cliente(bd_migrada: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARGOS_DATABASE_URL", bd_migrada)
    get_config.cache_clear()
    from argos_ejemplo.app import app

    with TestClient(app) as c:
        yield c
    get_config.cache_clear()


def test_salud_con_dependencias_ok(cliente: TestClient) -> None:
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json()["comprobaciones"] == {"postgres": "ok", "diario": "ok"}


def test_escribe_y_verifica_asientos(cliente: TestClient) -> None:
    r = cliente.post("/demo/asientos", params={"n": 10})
    assert r.status_code == 200 and r.json()["escritos"] == 10
    v = cliente.get("/diario/verificacion").json()
    assert v["integro"] and v["cabeza_seq"] == r.json()["ultimo_seq"]


def test_limite_de_asientos_por_peticion(cliente: TestClient) -> None:
    assert cliente.post("/demo/asientos", params={"n": 5000}).status_code == 422


def test_sin_configuracion_no_arranca(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARGOS_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    get_config.cache_clear()
    from argos_ejemplo.app import app

    with pytest.raises(ConfiguracionError), TestClient(app):
        pass
    get_config.cache_clear()
