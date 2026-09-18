"""ARG-069 · the verifier container answers the same report as the library, and nothing else."""

import httpx
import pytest

from argos_verifier.checks import verify_bundle

from .test_verifier_bundle import _exported

pytestmark = pytest.mark.integration

VERIFIER = "http://127.0.0.1:8007"


def test_the_container_is_up() -> None:
    assert httpx.get(f"{VERIFIER}/health", timeout=5).json() == {"status": "ok"}


def test_the_container_gives_the_report_of_the_library(migrated_db: str) -> None:
    bundle = _exported(migrated_db)
    response = httpx.post(f"{VERIFIER}/verify", json=bundle, timeout=30)
    assert response.status_code == 200
    assert response.json() == verify_bundle(bundle).as_dict()
    assert response.json()["ok"] is True


def test_the_container_has_no_other_door() -> None:
    assert httpx.get(f"{VERIFIER}/docs", timeout=5).status_code == 404
    assert httpx.get(f"{VERIFIER}/verify", timeout=5).status_code == 405
