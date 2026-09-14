"""Migrador auditable: SQL numerado, checksum y asiento en el diario (ARG-005)."""

import hashlib
import re
from pathlib import Path
from typing import Any

import psycopg

from .diario import canonizar
from .errors import IntegridadError

_NOMBRE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_BLOQUEO = "SELECT pg_advisory_lock(hashtext('argos.migraciones'))"
_DESBLOQUEO = "SELECT pg_advisory_unlock(hashtext('argos.migraciones'))"


def listar(carpeta: Path) -> list[tuple[int, Path]]:
    encontradas: list[tuple[int, Path]] = []
    for ruta in sorted(carpeta.glob("*.sql")):
        m = _NOMBRE.match(ruta.name)
        if m is None:
            raise ValueError(f"nombre de migración inválido: {ruta.name} (formato NNNN_nombre.sql)")
        encontradas.append((int(m.group(1)), ruta))
    versiones = [v for v, _ in encontradas]
    if len(set(versiones)) != len(versiones):
        raise ValueError("hay versiones de migración duplicadas")
    return sorted(encontradas)


def checksum(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _aplicadas(conn: psycopg.Connection[Any]) -> dict[int, str]:
    fila = conn.execute("SELECT to_regclass('argos.schema_version') IS NOT NULL").fetchone()
    if fila is None or not fila[0]:
        return {}
    filas = conn.execute("SELECT version, checksum FROM argos.schema_version")
    return {int(v): str(c) for v, c in filas}


def aplicar(dsn: str, carpeta: Path) -> list[int]:
    """Aplica en orden las migraciones pendientes; cada una en su transacción con su asiento."""
    pendientes = listar(carpeta)
    nuevas: list[int] = []
    with psycopg.connect(dsn) as conn:
        conn.execute(_BLOQUEO)
        conn.commit()
        try:
            hechas = _aplicadas(conn)
            conn.commit()
            for version, ruta in pendientes:
                suma = checksum(ruta)
                if version in hechas:
                    if hechas[version] != suma:
                        raise IntegridadError(
                            f"la migración {version} ha cambiado después de aplicarse",
                            detalles={"version": version},
                        )
                    continue
                with conn.transaction():
                    conn.execute(ruta.read_bytes())
                    conn.execute(
                        "INSERT INTO argos.schema_version (version, checksum) VALUES (%s, %s)",
                        (version, suma),
                    )
                    conn.execute(
                        "SELECT argos.journal_append(%s, %s, %s)",
                        (
                            "system:migrator",
                            "schema.migrate",
                            canonizar({"version": version, "checksum": suma}),
                        ),
                    )
                nuevas.append(version)
        finally:
            conn.rollback()
            conn.execute(_DESBLOQUEO)
            conn.commit()
    return nuevas
