"""Cliente PostgreSQL del diario v1: registrar, leer y verificar (ADR-0002)."""

from collections.abc import Iterator
from typing import Any

import psycopg

from .diario import GENESIS, Asiento, ResultadoVerificacion, canonizar, verificar_asientos

_LEER = """
    SELECT seq, at_canon, actor, action, payload_canon, prev_hash, entry_hash
      FROM argos.audit_journal
     WHERE seq >= %(desde)s AND (%(hasta)s::bigint IS NULL OR seq <= %(hasta)s)
     ORDER BY seq
"""


class DiarioPostgres:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def registrar(
        self,
        actor: str,
        action: str,
        payload: dict[str, Any],
        conn: psycopg.Connection[Any] | None = None,
    ) -> int:
        """Añade un asiento. Con `conn`, forma parte de la transacción del llamador."""
        canon = canonizar(payload)
        if conn is not None:
            return self._append(conn, actor, action, canon)
        with psycopg.connect(self._dsn) as propia:
            return self._append(propia, actor, action, canon)

    @staticmethod
    def _append(conn: psycopg.Connection[Any], actor: str, action: str, canon: str) -> int:
        fila = conn.execute(
            "SELECT argos.journal_append(%s, %s, %s)", (actor, action, canon)
        ).fetchone()
        if fila is None:
            raise RuntimeError("journal_append no devolvió secuencia")
        return int(fila[0])

    def leer(self, desde: int = 1, hasta: int | None = None) -> Iterator[Asiento]:
        with psycopg.connect(self._dsn) as conn, conn.cursor(name="lectura_diario") as cur:
            cur.itersize = 5000
            cur.execute(_LEER, {"desde": desde, "hasta": hasta})
            for seq, at_canon, actor, action, payload_canon, prev, entry in cur:
                yield Asiento(
                    seq, at_canon, actor, action, payload_canon, bytes(prev), bytes(entry)
                )

    def verificar(self, desde: int = 1, hasta: int | None = None) -> ResultadoVerificacion:
        prev = GENESIS
        if desde > 1:
            with psycopg.connect(self._dsn) as conn:
                fila = conn.execute(
                    "SELECT entry_hash FROM argos.audit_journal WHERE seq = %s", (desde - 1,)
                ).fetchone()
            if fila is None:
                raise ValueError(f"no existe el asiento {desde - 1} para enlazar el rango")
            prev = bytes(fila[0])
        return verificar_asientos(self.leer(desde, hasta), desde_seq=desde, prev_hash=prev)

    def cabeza(self) -> tuple[int, bytes]:
        with psycopg.connect(self._dsn) as conn:
            fila = conn.execute(
                "SELECT seq, entry_hash FROM argos.audit_journal ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return (0, GENESIS) if fila is None else (int(fila[0]), bytes(fila[1]))
