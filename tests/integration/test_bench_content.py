"""K-99 · the bootstrap of the bench publishes the library of its image as the signed content.

Against a migrated database and the Vault of development (transit key argos-content), through the
same small client of the Vault API the bootstrap uses: the first run publishes 1.0.0, verified on
disk as the engine will verify it; the second changes nothing.
"""

import importlib.util
import json
import os
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest

from argos_ontology.bundle import verify_on_disk
from argos_ontology.vocabulary import LIBRARY_DIR

pytestmark = pytest.mark.integration

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "platform"
    / "k8s"
    / "base"
    / "core"
    / "bootstrap"
    / "bootstrap.py"
)
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def _bootstrap() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vault(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """What vault_client() answers, with the root token of the development Vault."""
    request = urllib.request.Request(  # noqa: S310 - the development Vault
        f"{VAULT}/v1/{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Vault-Token": "root", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as answer:  # noqa: S310
        raw = answer.read()
    data = json.loads(raw) if raw else {}
    return data.get("data", data)


def test_the_library_is_published_once_and_then_left_in_force(migrated_db: str) -> None:
    bootstrap = _bootstrap()
    assert bootstrap.publish_content(migrated_db, _vault) == "content 1.0.0 published"
    verify_on_disk(migrated_db, "1.0.0", LIBRARY_DIR)
    assert bootstrap.publish_content(migrated_db, _vault) == "content 1.0.0 in force, as on disk"
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.ontology_bundles").fetchone() == (1,)
        refused = conn.execute(
            "SELECT count(*) FROM security.events WHERE kind LIKE 'content.%'"
        ).fetchone()
    assert refused == (0,), "comparing the library is not an alarm"
