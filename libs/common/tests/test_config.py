"""Typed configuration: fails at startup and never leaks values (ARG-001)."""

import os
from pathlib import Path

import pytest

from argos_common.config import ApplianceSize, Environment, LogLevel, load_config
from argos_common.errors import ConfigurationError

DSN = "postgresql://argos@127.0.0.1:55432/argos"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.upper().startswith("ARGOS_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # make sure no real .env file is read


def _fields(exc: ConfigurationError) -> list[str]:
    return [e["field"] for e in exc.details["errors"]]


def test_development_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    cfg = load_config()
    assert cfg.ENVIRONMENT is Environment.DEVELOPMENT
    assert cfg.APPLIANCE_SIZE is ApplianceSize.S
    assert cfg.LOG_LEVEL is LogLevel.INFO
    assert cfg.NATS_URL == "nats://127.0.0.1:4222"
    assert cfg.TEMPORAL_ADDRESS == "127.0.0.1:7233"


def test_missing_database_url_refuses_to_start() -> None:
    with pytest.raises(ConfigurationError) as exc:
        load_config()
    assert "DATABASE_URL" in _fields(exc.value)


def test_error_does_not_reveal_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_APPLIANCE_SIZE", "XXL-secret-value")
    with pytest.raises(ConfigurationError) as exc:
        load_config()
    assert "APPLIANCE_SIZE" in _fields(exc.value)
    assert "XXL-secret-value" not in str(exc.value.to_dict())


def test_environment_variables_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_APPLIANCE_SIZE", "M")
    monkeypatch.setenv("ARGOS_LOG_LEVEL", "DEBUG")
    cfg = load_config()
    assert cfg.APPLIANCE_SIZE is ApplianceSize.M
    assert cfg.LOG_LEVEL is LogLevel.DEBUG


def test_reads_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"ARGOS_DATABASE_URL={DSN}\nARGOS_APPLIANCE_SIZE=L\n", encoding="utf-8"
    )
    assert load_config().APPLIANCE_SIZE is ApplianceSize.L


def _production(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("ARGOS_ENVIRONMENT", "production")
    monkeypatch.setenv("ARGOS_DATABASE_URL", "postgresql://svc_api@db.argos.internal:5432/argos")
    monkeypatch.setenv("ARGOS_WORM_STORAGE_PATH", "/srv/argos/worm")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def test_valid_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch)
    assert load_config().ENVIRONMENT is Environment.PRODUCTION


def test_production_rejects_local_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch, ARGOS_DATABASE_URL=DSN)
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_config()


def test_production_requires_absolute_worm_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch, ARGOS_WORM_STORAGE_PATH="./data/worm")
    with pytest.raises(ConfigurationError):
        load_config()


def test_production_requires_json_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch, ARGOS_LOG_FORMAT_JSON="false")
    with pytest.raises(ConfigurationError):
        load_config()
