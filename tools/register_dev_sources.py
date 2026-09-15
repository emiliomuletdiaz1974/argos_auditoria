"""Register the simulated development sources: argos.systems rows and their Vault credentials.

Development only. The credentials are trivial and every run overwrites them, except the per-system
hash key, which is kept so that sample digests stay comparable across runs.

Usage: uv run --env-file .env.example python tools/register_dev_sources.py
"""

import json
import os
import secrets
from pathlib import Path
from typing import Any

import hvac
import psycopg
from hvac.exceptions import InvalidPath

from argos_common.config import get_config

CATALOG = Path(__file__).resolve().parents[1] / "deploy" / "dev" / "sources" / "systems.json"
VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "root")
_UPSERT = """
    INSERT INTO argos.systems (id, name, kind, environment, connection)
    VALUES (%s, %s, %s, 'development', %s::jsonb)
    ON CONFLICT (id) DO UPDATE
       SET name = EXCLUDED.name, kind = EXCLUDED.kind, connection = EXCLUDED.connection,
           updated_at = now()
"""


def load_catalog(path: Path = CATALOG) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["systems"]
    return systems


def _existing_hash_key(vault: hvac.Client, system_id: str) -> str | None:
    try:
        secret = vault.secrets.kv.v2.read_secret_version(
            path=f"connectors/{system_id}", mount_point="argos", raise_on_deleted_version=True
        )
    except InvalidPath:
        return None
    key = secret["data"]["data"].get("hash_key")
    return str(key) if key else None


def main() -> int:
    systems = load_catalog()
    vault = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
    with psycopg.connect(get_config().DATABASE_URL) as conn:
        for system in systems:
            connection = {
                "secret": f"connectors/{system['id']}",
                "connector": system.get("connector"),
                "config": system.get("config", {}),
            }
            conn.execute(
                _UPSERT, (system["id"], system["name"], system["kind"], json.dumps(connection))
            )
            hash_key = _existing_hash_key(vault, system["id"]) or secrets.token_hex(32)
            vault.secrets.kv.v2.create_or_update_secret(
                path=f"connectors/{system['id']}",
                secret={**system["credentials"], "hash_key": hash_key},
                mount_point="argos",
            )
    print(f"registered {len(systems)} development sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
