"""Shared helpers to open connectors against the simulated sources of make dev (F02-04)."""

import json
import os
from pathlib import Path
from typing import Any

import hvac
import psycopg

from argos_common.secret_stores import VaultSecretStore
from argos_connector.base import Connector
from argos_connector.budget import LoadBudget
from argos_connector.context import ConnectorContext
from argos_connector.credentials import load_credentials
from argos_connector.journal import QueryJournal
from argos_connector.minimize import ValueHasher

ROOT = Path(__file__).parents[2]
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
CATALOG: list[dict[str, Any]] = json.loads(
    (ROOT / "deploy" / "dev" / "sources" / "systems.json").read_text(encoding="utf-8")
)["systems"]


def catalog_system(name: str) -> dict[str, Any]:
    return next(s for s in CATALOG if s["name"] == name)


def connector_token() -> str:
    root = hvac.Client(url=VAULT, token="root")
    created = root.auth.token.create(policies=["svc-connector-sdk"], ttl="10m")
    return str(created["auth"]["client_token"])


def open_source_connector[C: Connector](name: str, cls: type[C], dsn: str, **budget: Any) -> C:
    """Register the catalog system in `dsn`, read its credentials with the SDK policy and open."""
    system = catalog_system(name)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, connection) VALUES (%s, %s, %s, '{}') "
            "ON CONFLICT (id) DO NOTHING",
            (system["id"], system["name"], system["kind"]),
        )
    credentials = load_credentials(VaultSecretStore(VAULT, connector_token()), system["id"])
    context = ConnectorContext(
        journal=QueryJournal(dsn, system["id"]),
        budget=LoadBudget(system["id"], {"queries_per_minute": 600, "burst": 100, **budget}),
        hasher=ValueHasher.from_hex(credentials["hash_key"]),
        credentials=credentials,
    )
    connector = cls(system["id"], system.get("config", {}), context)
    connector.open()
    return connector


def register_catalog_system(dsn: str, name: str, connector: str | None = None) -> str:
    """Insert the catalog system into argos.systems the way register_dev_sources.py does."""
    system = catalog_system(name)
    connection = {
        "secret": f"connectors/{system['id']}",
        "connector": connector or system["connector"],
        "config": system.get("config", {}),
    }
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, connection) VALUES (%s, %s, %s, %s::jsonb)",
            (system["id"], system["name"], system["kind"], json.dumps(connection)),
        )
    return str(system["id"])
