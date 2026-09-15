"""Prior and complete record of every probe sent to a customer system (ARG-012, P-04).

The chained journal entry and the connector_queries row are written in the same transaction,
before the SDK touches the customer system.
"""

import hashlib
import json
import uuid
from typing import Any

import psycopg

from argos_common.errors import IntegrityError
from argos_common.journal_pg import PostgresJournal

from .probes import ProbeSpec

_INSERT = """
    INSERT INTO argos.connector_queries
        (system_id, kind, target, statement, params, stmt_hash, journal_seq,
         status, finished_at, ok, error)
    VALUES (%(system_id)s, %(kind)s, %(target)s, %(statement)s, %(params)s::jsonb,
            %(stmt_hash)s, %(journal_seq)s, %(status)s,
            CASE WHEN %(status)s::text = 'rejected' THEN now() END,
            CASE WHEN %(status)s::text = 'rejected' THEN false END,
            %(error)s)
"""
_COMPLETE = """
    UPDATE argos.connector_queries
       SET status = CASE WHEN %(ok)s THEN 'completed' ELSE 'failed' END,
           finished_at = now(), ok = %(ok)s, duration_ms = %(duration_ms)s,
           rows_touched = %(rows)s, error = %(error)s
     WHERE journal_seq = %(journal_seq)s AND system_id = %(system_id)s AND finished_at IS NULL
"""


def statement_hash(statement: str | None) -> bytes:
    normalised = " ".join((statement or "").lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).digest()


class QueryJournal:
    def __init__(self, dsn: str, system_id: str) -> None:
        self.system_id = str(uuid.UUID(system_id))
        self._dsn = dsn
        self._journal = PostgresJournal(dsn)

    @property
    def actor(self) -> str:
        return f"system:connector:{self.system_id}"

    def register(self, spec: ProbeSpec) -> int:
        return self._record(spec, "query.emit", status="emitted", error=None)

    def reject(self, spec: ProbeSpec, reason: str) -> int:
        return self._record(spec, "query.reject", status="rejected", error=reason)

    def complete(
        self, journal_seq: int, *, ok: bool, duration_ms: int, rows: int, error: str | None = None
    ) -> None:
        with psycopg.connect(self._dsn) as conn:
            cursor = conn.execute(
                _COMPLETE,
                {
                    "ok": ok,
                    "duration_ms": duration_ms,
                    "rows": rows,
                    "error": error,
                    "journal_seq": journal_seq,
                    "system_id": self.system_id,
                },
            )
            if cursor.rowcount != 1:
                raise IntegrityError(
                    f"probe {journal_seq} has no open journal row",
                    details={"journal_seq": journal_seq},
                )

    def _record(self, spec: ProbeSpec, action: str, *, status: str, error: str | None) -> int:
        digest = statement_hash(spec.statement)
        payload: dict[str, Any] = {
            "system_id": self.system_id,
            "kind": spec.kind,
            "target": spec.target,
            "stmt_sha256": digest.hex(),
        }
        if error is not None:
            payload["reason"] = error
        with psycopg.connect(self._dsn) as conn:
            seq = self._journal.append(self.actor, action, payload, conn=conn)
            conn.execute(
                _INSERT,
                {
                    "system_id": self.system_id,
                    "kind": spec.kind,
                    "target": spec.target,
                    "statement": spec.statement,
                    "params": json.dumps(dict(spec.params), default=str, ensure_ascii=False),
                    "stmt_hash": digest,
                    "journal_seq": seq,
                    "status": status,
                    "error": error,
                },
            )
        return seq
