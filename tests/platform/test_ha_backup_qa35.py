"""Quality review QA-01 · failover of the size M and backup counts in their edge cases (QA-080,
QA-086). Pure: the database, Docker and restic are doubles that answer what each case needs."""

import contextlib
import importlib.util
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest

REPO = Path(__file__).resolve().parents[2]
HA = REPO / "platform" / "ha" / "size-m"
BACKUP = REPO / "platform" / "backup"


def _load(folder: Path, name: str) -> ModuleType:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


failover = _load(HA, "failover")
rejoin = _load(HA, "rejoin")
restore = _load(BACKUP, "restore_test")
backup = _load(BACKUP, "backup")

PRIMARY = "postgresql://argos@node-a/argos"
REPLICA = "postgresql://argos@node-b/argos"


class Conn:
    """A connection whose answers depend on the statement."""

    def __init__(self, answers: dict[str, Any], log: list[str]) -> None:
        self.answers, self.log = answers, log

    def __enter__(self) -> "Conn":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, *_: Any) -> "Conn":
        self.log.append(sql)
        self._row = next((row for key, row in self.answers.items() if key in sql), (1,))
        return self

    def fetchone(self) -> Any:
        return self._row


def _database(monkeypatch: pytest.MonkeyPatch, nodes: dict[str, Any]) -> list[str]:
    """`nodes[dsn]` is an exception to raise or the answers of that node."""
    log: list[str] = []

    def connect(dsn: str, **_: Any) -> Conn:
        node = nodes[dsn]
        if isinstance(node, BaseException):
            raise node
        return Conn(node, log)

    monkeypatch.setattr(failover.psycopg, "connect", connect)
    return log


def test_a_primary_that_refuses_the_password_is_not_a_primary_that_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA-080: an authentication error means the server answered; promoting then splits the
    brain."""
    log = _database(
        monkeypatch,
        {
            PRIMARY: psycopg.errors.InvalidPassword("password authentication failed"),
            REPLICA: {"pg_is_in_recovery": (True, 3)},
        },
    )
    code = failover.main(["--primary-dsn", PRIMARY, "--replica-dsn", REPLICA, "--confirm"])
    assert code != 0
    assert not any("pg_promote" in sql for sql in log)


def test_a_replica_that_never_replayed_has_an_unknown_lag_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database(monkeypatch, {REPLICA: {"pg_is_in_recovery": (True, None)}})
    assert failover.standby_lag(REPLICA) == (True, None)


def test_a_promotion_that_did_not_happen_is_not_a_failover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA-080: `pg_promote` answers false when it did not promote in time."""
    log = _database(
        monkeypatch,
        {
            PRIMARY: psycopg.OperationalError("connection refused"),
            REPLICA: {"pg_is_in_recovery": (True, 3), "pg_promote": (False,)},
        },
    )
    journal: list[Any] = []
    monkeypatch.setattr(failover, "PostgresJournal", lambda dsn: journal.append(dsn))
    code = failover.main(["--primary-dsn", PRIMARY, "--replica-dsn", REPLICA, "--confirm"])
    assert code != 0
    assert any("pg_promote" in sql for sql in log)
    assert journal == [], "nothing is verified or recorded after a promotion that failed"


def test_rejoin_without_confirm_empties_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """QA-080: rejoin deletes the data volume of a node: a drill unless it is confirmed."""
    roles = {PRIMARY: "down", REPLICA: "primary"}
    monkeypatch.setattr(rejoin, "role_of", lambda dsn: roles[dsn])
    recloned: list[str] = []
    monkeypatch.setattr(
        rejoin.ComposeNodes, "reclone", lambda self, node, primary: recloned.append(node)
    )
    args = ["--node", "ha-node-a", "--node-dsn", PRIMARY, "--primary", "ha-node-b",
            "--primary-dsn", REPLICA, "--compose-file", "compose.yaml"]  # fmt: skip
    assert rejoin.main(args) == 0
    assert recloned == []


# ---------- QA-086 ----------


class Restic:
    def ensure(self) -> None: ...

    def backup(self, paths: Sequence[str], tag: str, mounts: Any) -> str:
        return f"snap-{tag}"

    def forget_and_check(self) -> None: ...


class Vault:
    def kv_tree(self) -> dict[str, Any]:
        return {}


def test_the_counts_of_a_backup_are_the_ones_of_its_dump(tmp_path: Path) -> None:
    """QA-086: the counts were taken after the dump; rows written in between gave a false
    critical alert. They are taken in the snapshot the dump reads."""
    events: list[str] = []
    dumps: list[list[str]] = []
    written: dict[str, Any] = {}

    def run(command: list[str], stdin: bytes | None = None) -> bytes:
        if any("pg_dump " in part for part in command):
            events.append("dump")
            dumps.append(command)
        return b""

    @contextlib.contextmanager
    def snapshot() -> Iterator[tuple[str, dict[str, int]]]:
        events.append("snapshot")
        yield "00000003-00000002-1", {"argos.findings": 7}
        events.append("released")

    real_workspace = backup.workspace

    @contextlib.contextmanager
    def keeping() -> Iterator[Path]:
        with real_workspace() as staging:
            yield staging
            counts = staging / "db" / "counts.json"
            written.update(json.loads(counts.read_text(encoding="utf-8")))

    backup.workspace = keeping
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    try:
        backup.backup(
            Restic(), run, Vault(), tmp_path / "compose.yaml", "vol", "svc", "pw", snapshot
        )
    finally:
        backup.workspace = real_workspace
    assert events == ["snapshot", "dump", "released"]
    assert "00000003-00000002-1" in dumps[0]
    assert written == {"snapshot": "00000003-00000002-1", "tables": {"argos.findings": 7}}


def test_counts_of_the_same_snapshot_are_compared_exactly(tmp_path: Path) -> None:
    """QA-086: with the counts of its own snapshot, a copy with rows missing is a broken copy,
    not only a copy with a table at zero."""
    folder = tmp_path / "staging" / "db"
    folder.mkdir(parents=True)
    (folder / "counts.json").write_text(
        json.dumps({"snapshot": "s", "tables": {"argos.findings": 7}}), encoding="utf-8"
    )
    baseline = restore.baseline_counts(tmp_path, {"argos.findings": 9})
    assert baseline == {"argos.findings": 7}
    assert restore.exact_counts(tmp_path)
    assert restore.compare_counts(baseline, {"argos.findings": 6}, exact=True)
    assert restore.compare_counts(baseline, {"argos.findings": 7}, exact=True) == []
