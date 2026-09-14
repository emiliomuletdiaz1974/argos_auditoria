"""Pruebas unitarias de configuración tipada (Componente ARG-001)."""

import pytest
from argos_comun.config import ArgosConfig, TallaAppliance


def test_config_defaults() -> None:
    cfg = ArgosConfig()
    assert cfg.VERSION == "0.1.0-alpha"
    assert cfg.ENVIRONMENT == "development"
    assert cfg.TALLA == TallaAppliance.S
    assert "postgresql://" in cfg.DATABASE_URL
    assert cfg.WORM_STORAGE_PATH == "./data/worm"


def test_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_ENVIRONMENT", "production")
    monkeypatch.setenv("ARGOS_TALLA", "M")
    monkeypatch.setenv("ARGOS_LOG_LEVEL", "DEBUG")

    cfg = ArgosConfig()
    assert cfg.ENVIRONMENT == "production"
    assert cfg.TALLA == TallaAppliance.M
    assert cfg.LOG_LEVEL == "DEBUG"
