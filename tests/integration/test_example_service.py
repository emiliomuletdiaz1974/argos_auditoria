"""Example service in-process against a migrated database."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argos_common.config import get_config
from argos_common.errors import ConfigurationError

pytestmark = pytest.mark.integration


@pytest.fixture
def client(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARGOS_DATABASE_URL", migrated_db)
    get_config.cache_clear()
    from argos_example.app import app

    with TestClient(app) as c:
        yield c
    get_config.cache_clear()


def test_health_with_healthy_dependencies(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["checks"] == {"postgres": "ok", "journal": "ok"}


def test_writes_and_verifies_entries(client: TestClient) -> None:
    r = client.post("/demo/entries", params={"n": 10})
    assert r.status_code == 200 and r.json()["written"] == 10
    v = client.get("/journal/verification").json()
    assert v["intact"] and v["head_seq"] == r.json()["last_seq"]


def test_entries_per_request_limit(client: TestClient) -> None:
    assert client.post("/demo/entries", params={"n": 5000}).status_code == 422


def test_refuses_to_start_without_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ARGOS_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    get_config.cache_clear()
    from argos_example.app import app

    with pytest.raises(ConfigurationError), TestClient(app):
        pass
    get_config.cache_clear()
