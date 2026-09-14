"""PostgreSQL client for journal v1: append, read and verify (ADR-0002)."""

from collections.abc import Iterator
from typing import Any

import psycopg

from .journal import GENESIS, JournalEntry, VerificationResult, canonicalize, verify_entries

_READ = """
    SELECT seq, at_canon, actor, action, payload_canon, prev_hash, entry_hash
      FROM argos.audit_journal
     WHERE seq >= %(from_seq)s AND (%(to_seq)s::bigint IS NULL OR seq <= %(to_seq)s)
     ORDER BY seq
"""


class PostgresJournal:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def append(
        self,
        actor: str,
        action: str,
        payload: dict[str, Any],
        conn: psycopg.Connection[Any] | None = None,
    ) -> int:
        """Append an entry. With `conn`, it joins the caller's transaction."""
        canon = canonicalize(payload)
        if conn is not None:
            return self._append(conn, actor, action, canon)
        with psycopg.connect(self._dsn) as own:
            return self._append(own, actor, action, canon)

    @staticmethod
    def _append(conn: psycopg.Connection[Any], actor: str, action: str, canon: str) -> int:
        row = conn.execute(
            "SELECT argos.journal_append(%s, %s, %s)", (actor, action, canon)
        ).fetchone()
        if row is None:
            raise RuntimeError("journal_append returned no sequence")
        return int(row[0])

    def read(self, from_seq: int = 1, to_seq: int | None = None) -> Iterator[JournalEntry]:
        with psycopg.connect(self._dsn) as conn, conn.cursor(name="journal_read") as cur:
            cur.itersize = 5000
            cur.execute(_READ, {"from_seq": from_seq, "to_seq": to_seq})
            for seq, at_canon, actor, action, payload_canon, prev, entry in cur:
                yield JournalEntry(
                    seq, at_canon, actor, action, payload_canon, bytes(prev), bytes(entry)
                )

    def verify(self, from_seq: int = 1, to_seq: int | None = None) -> VerificationResult:
        prev = GENESIS
        if from_seq > 1:
            with psycopg.connect(self._dsn) as conn:
                row = conn.execute(
                    "SELECT entry_hash FROM argos.audit_journal WHERE seq = %s", (from_seq - 1,)
                ).fetchone()
            if row is None:
                raise ValueError(f"entry {from_seq - 1} does not exist to link the range")
            prev = bytes(row[0])
        return verify_entries(self.read(from_seq, to_seq), from_seq=from_seq, prev_hash=prev)

    def head(self) -> tuple[int, bytes]:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT seq, entry_hash FROM argos.audit_journal ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return (0, GENESIS) if row is None else (int(row[0]), bytes(row[1]))
