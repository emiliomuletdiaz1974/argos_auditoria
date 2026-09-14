"""Configuración tipada: falla al arrancar y no filtra valores (ARG-001)."""

import os
from pathlib import Path

import pytest

from argos_comun.config import Entorno, NivelLog, TallaAppliance, cargar_config
from argos_comun.errors import ConfiguracionError

DSN = "postgresql://argos@127.0.0.1:55432/argos"


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for clave in list(os.environ):
        if clave.upper().startswith("ARGOS_"):
            monkeypatch.delenv(clave)
    monkeypatch.chdir(tmp_path)  # que no lea un .env real


def _campos(exc: ConfiguracionError) -> list[str]:
    return [e["campo"] for e in exc.detalles["errores"]]


def test_valores_por_defecto_en_desarrollo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    cfg = cargar_config()
    assert cfg.ENVIRONMENT is Entorno.DESARROLLO
    assert cfg.TALLA is TallaAppliance.S
    assert cfg.LOG_LEVEL is NivelLog.INFO
    assert cfg.NATS_URL == "nats://127.0.0.1:4222"
    assert cfg.TEMPORAL_ADDRESS == "127.0.0.1:7233"


def test_sin_database_url_no_arranca() -> None:
    with pytest.raises(ConfiguracionError) as exc:
        cargar_config()
    assert "DATABASE_URL" in _campos(exc.value)


def test_el_error_no_revela_el_valor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_TALLA", "XXL-valor-secreto")
    with pytest.raises(ConfiguracionError) as exc:
        cargar_config()
    assert "TALLA" in _campos(exc.value)
    assert "XXL-valor-secreto" not in str(exc.value.to_dict())


def test_variables_de_entorno_sobrescriben(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_TALLA", "M")
    monkeypatch.setenv("ARGOS_LOG_LEVEL", "DEBUG")
    cfg = cargar_config()
    assert cfg.TALLA is TallaAppliance.M
    assert cfg.LOG_LEVEL is NivelLog.DEBUG


def test_lee_fichero_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"ARGOS_DATABASE_URL={DSN}\nARGOS_TALLA=L\n", encoding="utf-8")
    assert cargar_config().TALLA is TallaAppliance.L


def _produccion(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("ARGOS_ENVIRONMENT", "production")
    monkeypatch.setenv("ARGOS_DATABASE_URL", "postgresql://svc_api@db.argos.internal:5432/argos")
    monkeypatch.setenv("ARGOS_WORM_STORAGE_PATH", "/srv/argos/worm")
    for clave, valor in extra.items():
        monkeypatch.setenv(clave, valor)


def test_produccion_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    _produccion(monkeypatch)
    assert cargar_config().ENVIRONMENT is Entorno.PRODUCCION


def test_produccion_rechaza_base_de_datos_local(monkeypatch: pytest.MonkeyPatch) -> None:
    _produccion(monkeypatch, ARGOS_DATABASE_URL=DSN)
    with pytest.raises(ConfiguracionError, match="configuración inválida"):
        cargar_config()


def test_produccion_exige_ruta_worm_absoluta(monkeypatch: pytest.MonkeyPatch) -> None:
    _produccion(monkeypatch, ARGOS_WORM_STORAGE_PATH="./data/worm")
    with pytest.raises(ConfiguracionError):
        cargar_config()


def test_produccion_exige_logs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _produccion(monkeypatch, ARGOS_LOG_FORMAT_JSON="false")
    with pytest.raises(ConfiguracionError):
        cargar_config()
