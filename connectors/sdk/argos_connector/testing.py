"""Write-attempt harness and in-memory doubles shared by every connector's tests (ARG-011).

The harness tries to write through every path a connector could offer; each connector's test
suite runs it before any read test is written.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from argos_common.errors import ReadOnlyViolationError

from .base import Connector
from .context import ConnectorContext, ProbeBudget, ProbeJournal
from .minimize import ValueHasher
from .probes import ProbeSpec

SQL_WRITE_ATTEMPTS: tuple[str, ...] = (
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET a = 1",
    "DELETE FROM t",
    "MERGE INTO t USING s ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET a = 1",
    "CREATE TABLE x (a INT)",
    "DROP TABLE t",
    "ALTER TABLE t ADD COLUMN b INT",
    "TRUNCATE TABLE t",
    "GRANT SELECT ON t TO someone",
    "COPY t TO '/tmp/x'",
    "CALL p()",
    "EXEC sp_who",
    "SELECT * INTO t2 FROM t",
    "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
    "SELECT 1; DELETE FROM t",
    "/* hidden */ SELECT 1; DROP TABLE t",
    "SELECT nextval('s')",
    "SELECT * FROM t FOR UPDATE",
    "EXPLAIN ANALYZE DELETE FROM t",
    "SET search_path = x",
    "BEGIN",
    "SELECT pg_terminate_backend(123)",
    "LOCK TABLE t",
    "VACUUM t",
    "SELECT pg_sleep(100)",
    "SELECT * FROM dblink('dbname=x', 'DELETE FROM t RETURNING 1') AS r(a INT)",
    "SELECT * FROM OPENQUERY(srv, 'UPDATE t SET a = 1')",
    "SELECT * FROM OPENDATASOURCE('SQLNCLI', 'Data Source=x').db.dbo.t",
    "SELECT UTL_HTTP.REQUEST('http://collector.example/x') FROM dual",
    "SELECT sys.utl_inaddr.get_host_address('x') FROM dual",
    "SELECT pg_advisory_lock(1)",
    "SELECT pg_try_advisory_lock(1)",
    "SELECT pg_stat_file('postgresql.conf')",
    "SELECT lo_get(1)",
    "SELECT query_to_xml('DELETE FROM t RETURNING 1', true, true, '')",
    "SELECT xp_dirtree('c:/')",
    "SELECT release_lock('x')",
)
HTTP_WRITE_METHODS: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE")
_WRITE_NAME = re.compile(
    r"(^|_)(insert|update|delete|write|put|post|patch|store|move|copy|modify|add|remove|rename"
    r"|drop|create|upload|unlink|mkdir|rmdir|truncate|grant|revoke|chmod|chown|set_acl)(_|$)"
)


@dataclass
class JournalRecord:
    seq: int
    spec: ProbeSpec
    action: str
    outcome: dict[str, Any] | None = None


class InMemoryJournal:
    def __init__(self) -> None:
        self.records: list[JournalRecord] = []

    def _append(self, spec: ProbeSpec, action: str, outcome: dict[str, Any] | None) -> int:
        record = JournalRecord(len(self.records) + 1, spec, action, outcome)
        self.records.append(record)
        return record.seq

    def register(self, spec: ProbeSpec) -> int:
        return self._append(spec, "query.emit", None)

    def reject(self, spec: ProbeSpec, reason: str) -> int:
        return self._append(spec, "query.reject", {"reason": reason})

    def complete(
        self, journal_seq: int, *, ok: bool, duration_ms: int, rows: int, error: str | None = None
    ) -> None:
        record = self.records[journal_seq - 1]
        if record.action != "query.emit" or record.outcome is not None:
            raise AssertionError(f"probe {journal_seq} is not open")
        record.outcome = {"ok": ok, "duration_ms": duration_ms, "rows": rows, "error": error}

    @property
    def emitted(self) -> list[JournalRecord]:
        return [r for r in self.records if r.action == "query.emit"]

    @property
    def rejected(self) -> list[JournalRecord]:
        return [r for r in self.records if r.action == "query.reject"]


class NoBudget:
    def __init__(
        self, max_rows_per_probe: int = 10_000, fail_with: Exception | None = None
    ) -> None:
        self._max_rows = max_rows_per_probe
        self.fail_with = fail_with
        self.acquired = 0
        self.latencies: list[int] = []

    @property
    def max_rows_per_probe(self) -> int:
        return self._max_rows

    def acquire(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.acquired += 1

    def observe_latency(self, ms: int) -> None:
        self.latencies.append(ms)


def make_context(
    credentials: Mapping[str, str] | None = None,
    *,
    journal: ProbeJournal | None = None,
    budget: ProbeBudget | None = None,
    hash_key: bytes = bytes(range(32)),
) -> ConnectorContext:
    return ConnectorContext(
        journal=journal or InMemoryJournal(),
        budget=budget or NoBudget(),
        hasher=ValueHasher(hash_key),
        credentials=dict(credentials or {}),
    )


def assert_no_write_surface(cls: type) -> None:
    offenders = [
        name
        for name in dir(cls)
        if not name.startswith("__") and _WRITE_NAME.search(name.strip("_").lower())
    ]
    if offenders:
        raise AssertionError(f"{cls.__name__} exposes write-like members: {offenders}")


def assert_sql_writes_rejected(connector: Connector, target: str = "t") -> None:
    for statement in SQL_WRITE_ATTEMPTS:
        try:
            connector.execute(ProbeSpec("check_config", target, statement))
        except ReadOnlyViolationError:
            continue
        raise AssertionError(f"write attempt was not rejected: {statement!r}")


def assert_http_writes_rejected(request: Callable[[str, str], object], path: str) -> None:
    for method in HTTP_WRITE_METHODS:
        try:
            request(method, path)
        except ReadOnlyViolationError:
            continue
        raise AssertionError(f"HTTP {method} was not rejected")
