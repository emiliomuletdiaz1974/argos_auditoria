"""ARG-089 · a backup is tried by restoring it (F09-12).

    uv run python platform/backup/restore_test.py [--repository PATH|URL]

1. restores the last copy of the database into a working folder;
2. starts a **disposable PostgreSQL of the same image** as the environment, with a random password,
   no published port and no network at all (`--network none`): it cannot reach production by
   mistake, because there is no route to it;
3. restores the roles (without passwords) and the dump, and reads everything through
   `docker exec`;
4. verifies the chain of the journal with the verifier of the journal v1, checks that its head is
   the same entry in production, verifies the chain of the security log, compares the rows of every
   table (and the nodes of the inventory graph) with production, and checks a sample of evidence
   objects of the copy against `evidence_index`;
5. writes the dated result in `argos.restore_tests`, the journal and the security log, which is
   what the alerts of Prometheus read.

The container and the folder are removed always, also when something fails. A failure is a result
like any other: it is recorded, and it is a critical alert.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import backup_common as common
import psycopg

from argos_common import security_log
from argos_common.journal import (
    GENESIS,
    Anomaly,
    JournalEntry,
    VerificationResult,
    canonicalize,
    verify_entries,
)
from argos_common.journal_pg import PostgresJournal

IMAGE = "argos-dev/postgres:16-age-vector"
EVIDENCE_BUCKET = "evidence"
EVIDENCE_SAMPLE = 5
READY_TIMEOUT = 120
SNAPSHOT_ID = re.compile(r"[0-9a-f]{8,64}")
SCHEMAS = ("argos", "security")
# The same query on both sides: every table of the schemas of the product, with its exact count.
COUNTS_SQL = (
    "SELECT coalesce(json_object_agg(t.table_schema || '.' || t.table_name,"
    " (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I',"
    " t.table_schema, t.table_name), false, true, '')))[1]::text::bigint), '{}')"
    " FROM information_schema.tables t"
    " WHERE t.table_schema IN ('argos', 'security') AND t.table_type = 'BASE TABLE'"
)
# AGE is preloaded on both sides (shared_preload_libraries), so no LOAD: a role without
# privileges could not run it. The names are qualified instead of changing the search path.
GRAPH_SQL = (
    "SELECT CASE WHEN EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'inventory')"
    " THEN (SELECT c::text::bigint FROM ag_catalog.cypher('inventory',"
    " $$ MATCH (n) RETURN count(n) $$) AS (c ag_catalog.agtype)) ELSE 0 END"
)
JOURNAL_SQL = (
    "SELECT coalesce(json_agg(json_build_object('seq', seq, 'at_canon', at_canon, 'actor', actor,"
    " 'action', action, 'payload_canon', payload_canon, 'prev_hash', encode(prev_hash, 'hex'),"
    " 'entry_hash', encode(entry_hash, 'hex')) ORDER BY seq), '[]') FROM argos.audit_journal"
)
SECURITY_SQL = (
    "SELECT coalesce(json_agg(json_build_object('seq', seq, 'at_canon', at_canon, 'actor', actor,"
    " 'kind', kind, 'payload_canon', payload_canon, 'prev_hash', encode(prev_hash, 'hex'),"
    " 'entry_hash', encode(entry_hash, 'hex'), 'source', source, 'outcome', outcome,"
    " 'detail', detail) ORDER BY seq), '[]') FROM security.events"
)


class Production(Protocol):
    def counts(self) -> dict[str, int]: ...
    def journal_hash(self, seq: int) -> bytes | None: ...


class Repository(Protocol):
    def latest(self, tag: str) -> common.Snapshot: ...
    def restore(self, snapshot: str, target: Path, include: Sequence[str] = ()) -> None: ...


@dataclass
class RestoreResult:
    tested_at: dt.datetime
    snapshot_id: str | None = None
    snapshot_time: dt.datetime | None = None
    result: str = "failed"
    reasons: list[str] = field(default_factory=list)
    journal_entries: int = 0
    journal_intact: bool | None = None
    security_events: int = 0
    security_intact: bool | None = None
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    evidence_checked: int = 0
    evidence_ok: bool | None = None
    duration_seconds: float = 0.0

    def as_row(self) -> dict[str, Any]:
        return {
            "tested_at": self.tested_at.isoformat(),
            "snapshot_id": self.snapshot_id,
            "snapshot_time": self.snapshot_time.isoformat() if self.snapshot_time else None,
            "result": self.result,
            "reasons": json.dumps(self.reasons, ensure_ascii=False),
            "journal_entries": self.journal_entries,
            "journal_intact": self.journal_intact,
            "security_events": self.security_events,
            "security_intact": self.security_intact,
            "counts": json.dumps(self.counts, sort_keys=True),
            "evidence_checked": self.evidence_checked,
            "evidence_ok": self.evidence_ok,
            "duration_seconds": round(self.duration_seconds, 1),
        }


# --------------------------------------------------------------------------- what is decided


def compare_counts(production: Mapping[str, int], restored: Mapping[str, int]) -> list[str]:
    """A table of production missing from the copy, or empty there while production has rows.

    The copy is older than production, so fewer rows is normal; and tables that production empties
    on purpose (idempotency keys, queues) may have more rows in the copy. Neither is a problem.
    """
    problems = []
    for table, rows in sorted(production.items()):
        if table not in restored:
            problems.append(f"{table} is missing from the copy")
        elif rows > 0 and restored[table] == 0:
            problems.append(f"{table} is empty in the copy and has {rows} rows in production")
    return problems


def _entry(row: Mapping[str, Any], action_key: str) -> JournalEntry:
    return JournalEntry(
        int(row["seq"]),
        str(row["at_canon"]),
        str(row["actor"]),
        str(row[action_key]),
        str(row["payload_canon"]),
        bytes.fromhex(str(row["prev_hash"])),
        bytes.fromhex(str(row["entry_hash"])),
    )


def verify_journal(rows: Sequence[Mapping[str, Any]]) -> VerificationResult:
    """The verifier of the journal v1 over the rows of the copy."""
    return verify_entries((_entry(row, "action") for row in rows), from_seq=1, prev_hash=GENESIS)


def verify_security(rows: Sequence[Mapping[str, Any]]) -> VerificationResult:
    """The same verifier with the genesis of the security log, and its columns against the hash."""
    mismatches = [
        Anomaly(int(row["seq"]), "columns do not match the hashed payload")
        for row in rows
        if canonicalize(
            {"detail": row["detail"], "outcome": row["outcome"], "source": row["source"]}
        )
        != row["payload_canon"]
    ]
    result = verify_entries(
        (_entry(row, "kind") for row in rows), from_seq=1, prev_hash=security_log.GENESIS
    )
    if not mismatches:
        return result
    anomalies = tuple(sorted((*result.anomalies, *mismatches), key=lambda a: a.seq))
    return VerificationResult(result.verified, result.head_seq, result.head_hash, anomalies)


# --------------------------------------------------------------------------- disposable pieces


@contextmanager
def workspace(parent: Path | None = None) -> Iterator[Path]:
    """A working folder that is removed whatever happens."""
    folder = Path(tempfile.mkdtemp(prefix="argos-restore-", dir=parent))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@dataclass
class Disposable:
    """The disposable PostgreSQL: reached only through `docker exec`."""

    name: str
    docker: common.Runner

    def exec(self, *args: str) -> bytes:
        return self.docker(["docker", "exec", self.name, *args])

    def sql(self, query: str, database: str = "argos") -> str:
        out = self.exec(
            "psql", "-U", "argos", "-d", database, "-v", "ON_ERROR_STOP=1", "-X", "-At", "-c", query
        )
        return out.decode("utf-8").strip()

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        # During its first start the image runs a temporary server on the socket only; the real one
        # listens on TCP. Loopback exists even without a network.
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.exec("pg_isready", "-q", "-h", "127.0.0.1", "-U", "argos")
                return
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)


@contextmanager
def ephemeral_postgres(docker: common.Runner, image: str, folder: Path) -> Iterator[Disposable]:
    """A PostgreSQL of `image` with no network and a random password, removed on the way out."""
    name = f"argos-restore-{secrets.token_hex(4)}"
    (folder / "pgpass").write_text(common.random_password(), encoding="utf-8")
    try:
        docker(
            [
                "docker", "run", "-d", "--name", name, "--network", "none",
                "--label", "org.argos.restore-test=true",
                "-v", f"{folder}:/restore:ro",
                "-e", "POSTGRES_USER=argos", "-e", "POSTGRES_DB=restore",
                "-e", "POSTGRES_PASSWORD_FILE=/restore/pgpass",
                "--entrypoint", "docker-entrypoint.sh",
                image, "postgres", "-c", "shared_preload_libraries=age",
            ]
        )  # fmt: skip
        box = Disposable(name, docker)
        box.wait_ready()
        yield box
    finally:
        with suppress(RuntimeError):  # it was never created: nothing to remove
            docker(["docker", "rm", "-f", "-v", name])


# --------------------------------------------------------------------------- the trial


def _verify(
    box: Disposable,
    production: Production,
    repository: Repository,
    folder: Path,
    snapshot_id: str,
    result: RestoreResult,
) -> None:
    journal = json.loads(box.sql(JOURNAL_SQL))
    checked = verify_journal(journal)
    result.journal_entries = checked.verified
    result.journal_intact = checked.intact
    if not checked.intact:
        first = checked.anomalies[0]
        result.reasons.append(f"journal broken at entry {first.seq}: {first.reason}")
    elif checked.head_seq and production.journal_hash(checked.head_seq) != checked.head_hash:
        result.journal_intact = False
        result.reasons.append(f"entry {checked.head_seq} of the copy is not the one of production")

    events = json.loads(box.sql(SECURITY_SQL))
    security = verify_security(events)
    result.security_events = security.verified
    result.security_intact = security.intact
    if not security.intact:
        first = security.anomalies[0]
        result.reasons.append(f"security log broken at event {first.seq}: {first.reason}")

    restored = {k: int(v) for k, v in json.loads(box.sql(COUNTS_SQL)).items()}
    restored["graph:inventory"] = int(box.sql(GRAPH_SQL) or 0)
    current = production.counts()
    result.counts = {
        table: {"production": current.get(table, 0), "restored": restored.get(table, 0)}
        for table in sorted(set(current) | set(restored))
    }
    result.reasons += compare_counts(current, restored)

    # A different sample in each copy, chosen by the id of the snapshot. `psql -c` takes no
    # parameters: the id is checked to be hexadecimal before it goes into the query.
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError(f"{snapshot_id!r} is not the id of a restic snapshot")
    sample = json.loads(
        box.sql(
            "SELECT coalesce(json_agg(json_build_object('key', object_key, 'sha256', sha256)),"  # noqa: S608
            " '[]') FROM (SELECT object_key, sha256 FROM argos.evidence_index"
            f" ORDER BY md5(object_key || '{snapshot_id}') LIMIT {EVIDENCE_SAMPLE}) s"
        )
    )
    result.evidence_checked = len(sample)
    if not sample:
        return
    evidence = repository.latest("evidence")
    target = folder / "evidence"
    target.mkdir()
    paths = [f"/evidence/objects/{EVIDENCE_BUCKET}/{item['key']}" for item in sample]
    repository.restore(evidence.id, target, paths)
    wrong = []
    for item in sample:
        restored_file = target / "evidence" / "objects" / EVIDENCE_BUCKET / item["key"]
        found = (
            hashlib.sha256(restored_file.read_bytes()).hexdigest()
            if restored_file.is_file()
            else None
        )
        if found != item["sha256"]:
            wrong.append(item["key"])
    result.evidence_ok = not wrong
    if wrong:
        result.reasons.append(f"{len(wrong)} evidence objects do not match evidence_index")


def restore_test(
    repository: Repository,
    docker: common.Runner,
    production: Production,
    image: str,
    record: Callable[[RestoreResult], None],
    scratch: Path | None = None,
) -> RestoreResult:
    """Restore the last copy, verify it, record the dated result. Never raises for the copy."""
    started = time.monotonic()
    result = RestoreResult(tested_at=dt.datetime.now(dt.UTC))
    try:
        snapshot = repository.latest("db")
        result.snapshot_id, result.snapshot_time = snapshot.id, snapshot.time
        with workspace(scratch) as folder:
            repository.restore(snapshot.id, folder)
            with ephemeral_postgres(docker, image, folder) as box:
                # The roles first (without passwords), so owners and grants restore as they were.
                box.exec(
                    "psql", "-U", "argos", "-d", "restore", "-q", "-X",
                    "-f", "/restore/staging/db/roles.sql",
                )  # fmt: skip
                box.exec(
                    "pg_restore", "-U", "argos", "-d", "restore", "-C", "--exit-on-error",
                    "/restore/staging/db/argos.dump",
                )  # fmt: skip
                _verify(box, production, repository, folder, snapshot.id, result)
        result.result = "failed" if result.reasons else "passed"
    except Exception as failure:  # noqa: BLE001 - a failed trial is a result, recorded below
        result.result = "failed"
        result.reasons.append(str(failure)[:500])
    result.duration_seconds = time.monotonic() - started
    record(result)
    return result


# --------------------------------------------------------------------------- production side


class PostgresProduction:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def counts(self) -> dict[str, int]:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(COUNTS_SQL).fetchone()
            graph = conn.execute(GRAPH_SQL).fetchone()
        counts = {k: int(v) for k, v in (row[0] if row else {}).items()}
        counts["graph:inventory"] = int(graph[0]) if graph and graph[0] is not None else 0
        return counts

    def journal_hash(self, seq: int) -> bytes | None:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT entry_hash FROM argos.audit_journal WHERE seq = %s", (seq,)
            ).fetchone()
        return bytes(row[0]) if row else None


def postgres_recorder(dsn: str) -> Callable[[RestoreResult], None]:
    """The result in `argos.restore_tests`, the journal and the security log."""

    def record(result: RestoreResult) -> None:
        row = result.as_row()
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO argos.restore_tests (tested_at, snapshot_id, snapshot_time, result,"
                " reasons, journal_entries, journal_intact, security_events, security_intact,"
                " counts, evidence_checked, evidence_ok, duration_seconds) VALUES"
                " (%(tested_at)s, %(snapshot_id)s, %(snapshot_time)s, %(result)s, %(reasons)s,"
                " %(journal_entries)s, %(journal_intact)s, %(security_events)s,"
                " %(security_intact)s, %(counts)s, %(evidence_checked)s, %(evidence_ok)s,"
                " %(duration_seconds)s)",
                row,
            )
        detail = {
            "snapshot": result.snapshot_id or "",
            "result": result.result,
            "journal_intact": bool(result.journal_intact),
            "evidence_checked": result.evidence_checked,
            "reason": (result.reasons[0] if result.reasons else "")[:200],
        }
        PostgresJournal(dsn).append(common.ACTOR, "backup.restore_tested", detail)
        outcome = "succeeded" if result.result == "passed" else "failed"
        log = security_log.log(dsn)
        log.record("backup.restore_tested", common.ACTOR, outcome, detail, source="argos-backup")
        log.flush()

    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", default=os.environ.get("ARGOS_BACKUP_REPOSITORY"))
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--db-host", default=os.environ.get("ARGOS_BACKUP_DB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--db-port", type=int, default=int(os.environ.get("ARGOS_BACKUP_DB_PORT", "55432"))
    )
    args = parser.parse_args(argv)
    if not args.repository:
        parser.error("--repository or ARGOS_BACKUP_REPOSITORY")
    vault = common.Vault(
        os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"), os.environ.get("VAULT_TOKEN", "root")
    )
    user, password, lease = vault.database_credential()
    try:
        dsn = common.database_url(user, password, args.db_host, args.db_port)
        with common.Restic(common.docker, args.repository, vault.restic_password()) as restic:
            result = restore_test(
                restic, common.docker, PostgresProduction(dsn), args.image, postgres_recorder(dsn)
            )
    finally:
        vault.revoke(lease)
    print(json.dumps(result.as_row(), ensure_ascii=False, indent=1))
    return 0 if result.result == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
