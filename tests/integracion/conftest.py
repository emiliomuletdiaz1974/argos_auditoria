"""Fixtures de integración: una base de datos nueva por test."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from argos_comun.migraciones import aplicar

DSN_ADMIN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
MIGRACIONES = Path(__file__).parents[2] / "services" / "api" / "migrations"

__all__ = ["DSN_ADMIN", "MIGRACIONES", "aplicar"]


@pytest.fixture
def bd_vacia() -> Iterator[str]:
    nombre = f"argos_prueba_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(DSN_ADMIN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
    base = DSN_ADMIN.rsplit("/", 1)[0]
    try:
        yield f"{base}/{nombre}"
    finally:
        with psycopg.connect(DSN_ADMIN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nombre))
            )


@pytest.fixture
def bd_migrada(bd_vacia: str) -> str:
    aplicar(bd_vacia, MIGRACIONES)
    return bd_vacia
