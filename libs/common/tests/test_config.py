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
    monkeypatch.setenv("ARGOS_OIDC_ISSUER", "https://id.argos.internal/realms/argos")
    monkeypatch.setenv("ARGOS_VAULT_ADDR", "https://vault.argos.internal:8200")
    monkeypatch.setenv("ARGOS_NATS_URL", "tls://nats.argos.internal:4222")
    monkeypatch.setenv("ARGOS_OPA_URL", "https://opa.argos.internal:8181")
    monkeypatch.setenv("ARGOS_LLM_LOCAL_ENDPOINT", "https://llm.argos.internal/v1")
    monkeypatch.setenv("ARGOS_NATS_USER", "inventory")
    monkeypatch.setenv("ARGOS_NATS_PASSWORD", "a-long-generated-secret")
    monkeypatch.setenv("ARGOS_OPA_TOKEN", "another-long-generated-secret")
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


def test_production_requires_https_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch, ARGOS_OIDC_ISSUER="http://id.argos.internal/realms/argos")
    with pytest.raises(ConfigurationError):
        load_config()


def test_development_oidc_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    cfg = load_config()
    assert cfg.OIDC_ISSUER == "http://127.0.0.1:8180/realms/argos"
    assert cfg.OIDC_AUDIENCE == "argos-api"


@pytest.mark.parametrize(
    ("variable", "value", "field"),
    [
        ("ARGOS_VAULT_ADDR", "http://vault.argos.internal:8200", "VAULT_ADDR"),
        ("ARGOS_VAULT_TOKEN", "root", "VAULT_TOKEN"),
        ("ARGOS_NATS_URL", "nats://nats.argos.internal:4222", "NATS_URL"),
        ("ARGOS_OPA_URL", "http://opa.argos.internal:8181", "OPA_URL"),
        ("ARGOS_LLM_LOCAL_ENDPOINT", "http://llm.argos.internal/v1", "LLM_LOCAL_ENDPOINT"),
    ],
)
def test_production_refuses_clear_or_development_endpoints(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, field: str
) -> None:
    # A token and verdict-deciding policies crossing the network in clear is not a deployment.
    _production(monkeypatch, **{variable: value})
    with pytest.raises(ConfigurationError) as refused:
        load_config()
    assert field in str(refused.value.details)
    assert value not in str(refused.value.details)


@pytest.mark.parametrize("missing", ["ARGOS_NATS_USER", "ARGOS_NATS_PASSWORD", "ARGOS_OPA_TOKEN"])
def test_production_requires_the_bus_and_policy_credentials(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _production(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ConfigurationError) as refused:
        load_config()
    assert missing.removeprefix("ARGOS_") in str(refused.value.details)


def test_the_bus_and_policy_secrets_never_print(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_NATS_PASSWORD", "dev-only-nats")
    monkeypatch.setenv("ARGOS_OPA_TOKEN", "dev-only-opa")
    shown = repr(load_config())
    assert "dev-only-nats" not in shown and "dev-only-opa" not in shown


def test_production_requires_json_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch, ARGOS_LOG_FORMAT_JSON="false")
    with pytest.raises(ConfigurationError):
        load_config()
