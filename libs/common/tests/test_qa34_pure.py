"""Quality review QA-01 · release manifest and production configuration in their edge cases
(QA-008, QA-010)."""

import os
from pathlib import Path

import pytest

from argos_common.config import load_config
from argos_common.errors import ConfigurationError
from argos_common.release import _image_name, build_manifest

DIGEST = "sha256:" + "a" * 64


def test_a_missing_sbom_folder_is_not_a_release_without_sboms(tmp_path: Path) -> None:
    """QA-008: given a folder that does not exist, the manifest was signed with no SBOM."""
    with pytest.raises(ValueError, match="SBOM"):
        build_manifest(
            "1.0.0", [{"ref": f"argos-api:1.0.0@{DIGEST}"}], tmp_path / "missing", "2026-09-28"
        )


@pytest.mark.parametrize(
    "ref",
    [
        f"registry.local:5000/argos-api@{DIGEST}",
        f"registry.local:5000/argos-api:1.0.0@{DIGEST}",
        f"argos-api:1.0.0@{DIGEST}",
        f"argos/argos-api@{DIGEST}",
    ],
)
def test_the_name_of_an_image_ignores_the_port_of_its_registry(ref: str) -> None:
    assert _image_name(ref) == "argos-api"


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    for key in list(os.environ):
        if key.upper().startswith("ARGOS_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    values = {
        "ARGOS_ENVIRONMENT": "production",
        "ARGOS_WORM_STORAGE_PATH": "/srv/argos/worm",
        "ARGOS_OIDC_ISSUER": "https://id.argos.internal/realms/argos",
        "ARGOS_VAULT_ADDR": "https://vault.argos.internal:8200",
        "ARGOS_NATS_URL": "tls://nats.argos.internal:4222",
        "ARGOS_OPA_URL": "https://opa.argos.internal:8181",
        "ARGOS_LLM_LOCAL_ENDPOINT": "https://llm.argos.internal/v1",
        "ARGOS_NATS_USER": "inventory",
        "ARGOS_NATS_PASSWORD": "a-long-generated-secret",
        "ARGOS_OPA_TOKEN": "another-long-generated-secret",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_production_requires_a_verified_connection_to_postgresql(
    production: pytest.MonkeyPatch,
) -> None:
    """QA-010: credentials and verdicts cross this link; without verify-full a man in the middle
    reads them."""
    for url in (
        "postgresql://svc_api@db.argos.internal:5432/argos",
        "postgresql://svc_api@db.argos.internal:5432/argos?sslmode=require",
    ):
        production.setenv("ARGOS_DATABASE_URL", url)
        with pytest.raises(ConfigurationError) as refused:
            load_config()
        assert "sslmode" in str(refused.value.details)
    production.setenv(
        "ARGOS_DATABASE_URL",
        "postgresql://svc_api@db.argos.internal:5432/argos?sslmode=verify-full",
    )
    assert load_config().DATABASE_URL.endswith("sslmode=verify-full")


def test_a_host_whose_name_contains_localhost_is_not_a_local_database(
    production: pytest.MonkeyPatch,
) -> None:
    """QA-010: the local database was detected by substring."""
    production.setenv(
        "ARGOS_DATABASE_URL",
        "postgresql://svc_api@pg.localhost-cluster.example:5432/argos?sslmode=verify-full",
    )
    assert load_config().DATABASE_URL.startswith("postgresql://svc_api@pg.localhost-cluster")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "127.0.0.2", "LOCALHOST"])
def test_a_local_database_is_still_refused(production: pytest.MonkeyPatch, host: str) -> None:
    production.setenv(
        "ARGOS_DATABASE_URL", f"postgresql://svc_api@{host}:5432/argos?sslmode=verify-full"
    )
    with pytest.raises(ConfigurationError):
        load_config()
