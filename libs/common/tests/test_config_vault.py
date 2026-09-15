"""ARG-009 · Vault settings of the services that open connectors (F03-02)."""

import pytest

from argos_common.config import load_config

DSN = "postgresql://argos@127.0.0.1:55432/argos"


def test_vault_defaults_to_the_local_development_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.delenv("ARGOS_VAULT_ADDR", raising=False)
    monkeypatch.delenv("ARGOS_VAULT_TOKEN", raising=False)
    cfg = load_config()
    assert cfg.VAULT_ADDR == "http://127.0.0.1:8200"
    assert cfg.VAULT_TOKEN is None


def test_vault_token_is_a_secret_that_never_prints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", DSN)
    monkeypatch.setenv("ARGOS_VAULT_TOKEN", "dev-only-vault-token")
    cfg = load_config()
    assert cfg.VAULT_TOKEN is not None
    assert cfg.VAULT_TOKEN.get_secret_value() == "dev-only-vault-token"
    assert "dev-only-vault-token" not in repr(cfg)
