"""Auditable migrator: numbered SQL, checksum and a journal entry per migration (ARG-005)."""

import hashlib
import re
from pathlib import Path
from typing import Any

import psycopg

from .errors import IntegrityError
from .journal import canonicalize

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_LOCK = "SELECT pg_advisory_lock(hashtext('argos.migrations'))"
_UNLOCK = "SELECT pg_advisory_unlock(hashtext('argos.migrations'))"


def list_migrations(directory: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        m = _NAME.match(path.name)
        if m is None:
            raise ValueError(f"invalid migration name: {path.name} (expected NNNN_name.sql)")
        found.append((int(m.group(1)), path))
    versions = [v for v, _ in found]
    if len(set(versions)) != len(versions):
        raise ValueError("duplicate migration versions")
    return sorted(found)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied(conn: psycopg.Connection[Any]) -> dict[int, str]:
    row = conn.execute("SELECT to_regclass('argos.schema_version') IS NOT NULL").fetchone()
    if row is None or not row[0]:
        return {}
    rows = conn.execute("SELECT version, checksum FROM argos.schema_version")
    return {int(v): str(c) for v, c in rows}


def apply_migrations(dsn: str, directory: Path) -> list[int]:
    """Apply pending migrations in order, each in its own transaction with its journal entry."""
    pending = list_migrations(directory)
    applied_now: list[int] = []
    with psycopg.connect(dsn) as conn:
        conn.execute(_LOCK)
        conn.commit()
        try:
            already_applied = _applied(conn)
            conn.commit()
            for version, path in pending:
                digest = checksum(path)
                if version in already_applied:
                    if already_applied[version] != digest:
                        raise IntegrityError(
                            f"migration {version} changed after being applied",
                            details={"version": version},
                        )
                    continue
                with conn.transaction():
                    conn.execute(path.read_bytes())
                    conn.execute(
                        "INSERT INTO argos.schema_version (version, checksum) VALUES (%s, %s)",
                        (version, digest),
                    )
                    conn.execute(
                        "SELECT argos.journal_append(%s, %s, %s)",
                        (
                            "system:migrator",
                            "schema.migrate",
                            canonicalize({"version": version, "checksum": digest}),
                        ),
                    )
                applied_now.append(version)
        finally:
            conn.rollback()
            conn.execute(_UNLOCK)
            conn.commit()
    return applied_now
