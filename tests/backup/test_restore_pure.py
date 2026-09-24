"""ARG-089 · the pure parts of the backup and of its restore test (F09-12).

A backup only exists when its restoration has been tried. These tests pin what the trial decides
without Docker: an empty table in the copy is a failure, a journal with one byte changed does not
verify, the disposable database and the working folder go away even when something fails, and the
restic password never travels in a command line.
"""

import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from argos_common.journal import GENESIS, canonicalize, compute_hash

REPO = Path(__file__).resolve().parents[2]
BACKUP = REPO / "platform" / "backup"


def _load(name: str) -> ModuleType:
    if str(BACKUP) not in sys.path:
        sys.path.insert(0, str(BACKUP))
    spec = importlib.util.spec_from_file_location(name, BACKUP / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load("backup_common")
restore = _load("restore_test")


def _chain(count: int, genesis: bytes = GENESIS) -> list[dict[str, Any]]:
    """Journal rows as the restored database gives them: hashes in hexadecimal."""
    rows, prev = [], genesis
    for seq in range(1, count + 1):
        at, payload = f"2026-09-24T10:00:0{seq}.000000Z", canonicalize({"n": seq})
        entry = compute_hash(seq, at, "system:test", "test.entry", payload, prev)
        rows.append(
            {"seq": seq, "at_canon": at, "actor": "system:test", "action": "test.entry",
             "payload_canon": payload, "prev_hash": prev.hex(), "entry_hash": entry.hex()}
        )  # fmt: skip
        prev = entry
    return rows


def test_the_comparison_of_counts_notices_an_empty_table() -> None:
    production = {"argos.campaigns": 12, "argos.audit_journal": 300, "argos.webhooks": 0}
    restored = {"argos.campaigns": 0, "argos.audit_journal": 290, "argos.webhooks": 0}
    assert restore.compare_counts(production, restored) == [
        "argos.campaigns is empty in the copy and has 12 rows in production"
    ]


def test_a_table_missing_from_the_copy_is_a_problem_too() -> None:
    problems = restore.compare_counts({"argos.findings": 3}, {})
    assert problems == ["argos.findings is missing from the copy"]


def test_a_copy_older_than_production_is_fine() -> None:
    assert restore.compare_counts({"argos.audit_journal": 300}, {"argos.audit_journal": 250}) == []


def test_a_restored_journal_verifies_when_nothing_changed() -> None:
    result = restore.verify_journal(_chain(3))
    assert result.intact and result.verified == 3


def test_a_restored_journal_with_one_byte_changed_is_broken() -> None:
    rows = _chain(3)
    rows[1]["payload_canon"] = rows[1]["payload_canon"].replace("2", "7")
    result = restore.verify_journal(rows)
    assert not result.intact
    assert result.anomalies[0].seq == 2


def test_the_security_log_verifies_with_its_own_genesis_and_columns() -> None:
    from argos_common.security_log import GENESIS as SECURITY_GENESIS

    rows = _chain(2, SECURITY_GENESIS)
    for row in rows:
        row["kind"] = row.pop("action")
        row["payload_canon"] = canonicalize(
            {"detail": {}, "outcome": "succeeded", "source": "test"}
        )
        row["detail"], row["outcome"], row["source"] = {}, "succeeded", "test"
    # rebuild the hashes over the new payloads
    prev = SECURITY_GENESIS
    for row in rows:
        entry = compute_hash(
            row["seq"], row["at_canon"], row["actor"], row["kind"], row["payload_canon"], prev
        )
        row["prev_hash"], row["entry_hash"], prev = prev.hex(), entry.hex(), entry
    assert restore.verify_security(rows).intact
    rows[0]["outcome"] = "refused"  # the column people query no longer matches the hash
    assert not restore.verify_security(rows).intact


class Docker:
    """Records every command; `fail_on` makes the first command containing it fail."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, args: Sequence[str], stdin: bytes | None = None) -> bytes:
        self.calls.append(list(args))
        if self.fail_on and self.fail_on in args:
            raise RuntimeError(f"{self.fail_on} failed")
        return b""


def test_the_disposable_database_and_the_folder_go_away_also_on_failure(tmp_path: Path) -> None:
    docker = Docker()
    image = "argos-dev/postgres:16-age-vector"
    with (
        pytest.raises(RuntimeError, match="boom"),
        restore.workspace(tmp_path) as work,
        restore.ephemeral_postgres(docker, image, work) as box,
    ):
        name = box.name
        raise RuntimeError("boom")
    assert not work.exists()
    assert ["docker", "rm", "-f", "-v", name] in docker.calls
    [started] = [c for c in docker.calls if c[:2] == ["docker", "run"]]
    assert started[started.index("--network") + 1] == "none", "no way to reach production"
    assert "-p" not in started and "--publish" not in started, "no published port"


class Restic:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def latest(self, tag: str) -> Any:
        if self.fail:
            raise RuntimeError("ciphertext verification failed")
        return common.Snapshot("abc12345", dt.datetime(2026, 9, 24, tzinfo=dt.UTC), tag)

    def restore(self, snapshot: str, target: Path, include: Sequence[str] = ()) -> None:
        return None


class Production:
    def counts(self) -> dict[str, int]:
        return {}

    def journal_hash(self, seq: int) -> bytes | None:
        return None


def test_a_failed_restore_is_recorded_as_failed_and_cleans_up(tmp_path: Path) -> None:
    recorded: list[Any] = []
    result = restore.restore_test(
        Restic(fail=True), Docker(), Production(), "image", recorded.append, tmp_path
    )
    assert result.result == "failed"
    assert "ciphertext verification failed" in result.reasons[0]
    assert recorded == [result]
    assert list(tmp_path.iterdir()) == [], "no working folder left behind"


def test_a_restore_that_breaks_half_way_still_removes_the_database(tmp_path: Path) -> None:
    docker = Docker(fail_on="pg_restore")
    result = restore.restore_test(Restic(), docker, Production(), "image", lambda r: None, tmp_path)
    assert result.result == "failed"
    assert any(c[:3] == ["docker", "rm", "-f"] for c in docker.calls)
    assert list(tmp_path.iterdir()) == []


def test_the_restic_password_never_goes_in_a_command(tmp_path: Path) -> None:
    docker = Docker()
    with common.Restic(docker, str(tmp_path / "repo"), "s3cr3t-restic-pw", tmp_path) as restic:
        restic.run(["snapshots", "--json"])
    command = docker.calls[-1]
    assert not any("s3cr3t-restic-pw" in arg for arg in command)
    assert "RESTIC_PASSWORD_FILE=/run/secrets/restic" in command
    assert common.RESTIC_IMAGE in command and "@sha256:" in common.RESTIC_IMAGE
    assert list(tmp_path.glob("restic-*")) == [], "the password file is gone after use"


def test_the_result_is_a_record_with_a_date_and_every_check() -> None:
    result = restore.RestoreResult(
        tested_at=dt.datetime(2026, 9, 24, tzinfo=dt.UTC), snapshot_id="abc", result="passed"
    )
    row = result.as_row()
    assert row["tested_at"] == "2026-09-24T00:00:00+00:00"
    assert json.loads(row["counts"]) == {}
    assert row["result"] == "passed"


def test_the_copy_is_compared_with_the_counts_of_its_own_moment(tmp_path: Path) -> None:
    """F09-99: production gains tables (a migration) and rows after the copy; that is not a
    broken copy. The backup keeps the counts of its moment, and the trial compares with those."""
    folder = tmp_path / "staging" / "db"
    folder.mkdir(parents=True)
    (folder / "counts.json").write_text(
        json.dumps({"argos.findings": 0, "argos.audit_journal": 250}), encoding="utf-8"
    )
    now = {"argos.findings": 10, "argos.audit_journal": 300, "argos.closed_sessions": 1}
    baseline = restore.baseline_counts(tmp_path, now)
    assert baseline == {"argos.findings": 0, "argos.audit_journal": 250}
    assert restore.compare_counts(baseline, {"argos.findings": 0, "argos.audit_journal": 250}) == []


def test_without_counts_of_its_moment_the_copy_is_compared_with_production(tmp_path: Path) -> None:
    now = {"argos.findings": 10}
    assert restore.baseline_counts(tmp_path, now) == now
