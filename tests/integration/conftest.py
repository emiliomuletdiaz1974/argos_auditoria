"""Integration fixtures: a fresh database per test."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from argos_common.migrations import apply_migrations

ADMIN_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
MIGRATIONS_DIR = Path(__file__).parents[2] / "services" / "api" / "migrations"

__all__ = ["ADMIN_DSN", "MIGRATIONS_DIR", "apply_migrations"]


@pytest.fixture
def empty_db() -> Iterator[str]:
    name = f"argos_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    base = ADMIN_DSN.rsplit("/", 1)[0]
    try:
        yield f"{base}/{name}"
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def migrated_db(empty_db: str) -> str:
    apply_migrations(empty_db, MIGRATIONS_DIR)
    return empty_db
