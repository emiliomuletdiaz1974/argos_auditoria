"""ARG-088 · a real diagnostic package of the development compose (F09-11).

The collector reads the running environment (services, health, events, logs and the journal) and
no value that Vault keeps under `argos/` appears in any file of the preview. The API then encrypts
exactly the reviewed preview, and the test key of support opens it to the same bytes.
"""

import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pyrage
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.routers.support import SupportDiagnostics
from argos_auth import Identity, JwtValidator
from argos_support import DiagnosticsStore, collect, open_package
from argos_support.cli import postgres_journal_tail
from argos_support.inspectors import ComposeInspector

from .conftest import ADMIN_DSN

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
VAULT = "http://127.0.0.1:8200"
API = "http://127.0.0.1:8000"
# Shorter values (`root`, `argos`, a port) are ordinary words of any log; the scrubber replaces
# them by pattern where they sit next to their name, not by value.
MIN_LENGTH = 8
# The simulated sources listen on the loopback of the developer machine, so their host in Vault is
# `127.0.0.1`: the address every service also writes when it answers its own healthcheck. It
# identifies nothing and Vault keeps it only next to the credentials of the source.
NOT_SECRET = {"127.0.0.1", "localhost"}


def _vault(method: str, path: str) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - the development Vault on the loopback
        f"{VAULT}/v1/{path}", method=method, headers={"X-Vault-Token": "root"}
    )
    with urllib.request.urlopen(request, timeout=10) as answer:  # noqa: S310
        return cast(dict[str, Any], json.loads(answer.read()))


def _vault_values(prefix: str = "") -> set[str]:
    """Every string value stored under `argos/`, walking the metadata tree."""
    values: set[str] = set()
    for key in _vault("LIST", f"argos/metadata/{prefix}")["data"]["keys"]:
        if key.endswith("/"):
            values |= _vault_values(prefix + key)
            continue
        data = _vault("GET", f"argos/data/{prefix}{key}")["data"]["data"]
        values |= {str(v) for v in data.values() if isinstance(v, str | int)}
    return values


class Admin:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="admin", name="admin", roles=frozenset({"platform_admin"}),
            amr=frozenset({"pwd", "otp"}),
        )  # fmt: skip


def test_a_real_package_carries_no_value_of_vault_and_opens_as_reviewed(tmp_path: Path) -> None:
    secrets = {v for v in _vault_values() if len(v) >= MIN_LENGTH and v not in NOT_SECRET}
    assert secrets, "the development Vault keeps secrets under argos/"
    version = REPO / "deploy" / "dev" / "update" / "version"
    preview = collect(
        ComposeInspector(COMPOSE),
        postgres_journal_tail(ADMIN_DSN),
        version.read_text(encoding="utf-8").strip() if version.exists() else None,
        dt.datetime.now(dt.UTC),
    )

    assert {"versions.txt", "health.json", "events.txt", "journal-tail.json"} <= set(preview.files)
    assert "logs/api.log" in preview.files and "logs/postgres.log" in preview.files
    listed = {entry["name"] for entry in json.loads(preview.index)["files"]}
    assert listed == set(preview.files)
    for name, data in {**preview.files, "INDEX.json": preview.index}.items():
        text = data.decode("utf-8")
        leaked = sorted(secret[:4] + "…" for secret in secrets if secret in text)
        assert not leaked, f"{name} carries values of Vault: {leaked}"
    rows = json.loads(preview.files["journal-tail.json"])
    assert rows and all(sorted(row) == ["action", "actor", "at", "seq"] for row in rows)

    identity = pyrage.x25519.Identity.generate()
    store = DiagnosticsStore(tmp_path)
    support = SupportDiagnostics(store, str(identity.to_public()))
    client = TestClient(create_app(cast(JwtValidator, Admin()), dsn=ADMIN_DSN, support=support))
    ident = store.request("user:admin")
    store.save(ident, preview)
    admin = {"Authorization": "Bearer admin"}
    shown = client.get(f"{API_PREFIX}/support/diagnostics/{ident}", headers=admin).json()
    answer = client.post(
        f"{API_PREFIX}/support/diagnostics/{ident}/package",
        json={"approved_index_sha256": shown["index_sha256"]},
        headers=admin,
    )
    assert answer.status_code == 200, answer.text
    opened = open_package(answer.content, str(identity))
    assert opened == {**preview.files, "INDEX.json": preview.index}


def test_the_deployed_api_offers_the_diagnostics_only_with_a_token() -> None:
    request = urllib.request.Request(  # noqa: S310 - the development API on the loopback
        f"{API}{API_PREFIX}/support/diagnostics", method="POST", data=b""
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=10)  # noqa: S310
    assert refused.value.code == 401, "the route is there, and closed"
