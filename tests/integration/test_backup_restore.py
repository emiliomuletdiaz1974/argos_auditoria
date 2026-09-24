"""ARG-089 · a real backup, a real restore test, and a corrupted copy that fails (F09-12).

The backup of the development environment goes to a repository of the test. Its restore test
brings up a disposable PostgreSQL without network, verifies the chain of the journal and of the
security log and records a dated row in `argos.restore_tests`. The same copy with its data packs
damaged fails the test, is recorded as failed and turns the metric the critical alert reads.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient

from argos_api.app import create_app
from argos_auth import JwtValidator

from .conftest import ADMIN_DSN

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
BACKUP = REPO / "platform" / "backup"
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
PROMETHEUS = "prom/prometheus:v2.54.1"


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
backup = _load("backup")


def _vault() -> Any:
    return common.Vault("http://127.0.0.1:8200", "root")


def _run(repository: Path) -> tuple[Any, Any]:
    """Back up into `repository`, then try it; both with a credential of `svc_backup`."""
    vault = _vault()
    user, password, lease = vault.database_credential()
    dsn = common.database_url(user, password, "127.0.0.1", 55432)
    try:
        with common.Restic(common.docker, str(repository), vault.restic_password()) as restic:
            snapshots = backup.backup(
                restic, common.docker, vault, COMPOSE, backup.EVIDENCE_VOLUME, user, password
            )
            result = restore.restore_test(
                restic,
                common.docker,
                restore.PostgresProduction(dsn),
                restore.IMAGE,
                restore.postgres_recorder(dsn),
            )
    finally:
        vault.revoke(lease)
    return snapshots, result


def _try_again(repository: Path) -> Any:
    vault = _vault()
    user, password, lease = vault.database_credential()
    dsn = common.database_url(user, password, "127.0.0.1", 55432)
    try:
        with common.Restic(common.docker, str(repository), vault.restic_password()) as restic:
            return restore.restore_test(
                restic,
                common.docker,
                restore.PostgresProduction(dsn),
                restore.IMAGE,
                restore.postgres_recorder(dsn),
            )
    finally:
        vault.revoke(lease)


def _row(snapshot: str | None, result: str) -> tuple[Any, ...] | None:
    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute(
            "SELECT result, journal_intact, security_intact, reasons FROM argos.restore_tests"
            " WHERE snapshot_id IS NOT DISTINCT FROM %s AND result = %s"
            " ORDER BY tested_at DESC LIMIT 1",
            (snapshot, result),
        ).fetchone()


def _metrics() -> str:
    app = create_app(cast(JwtValidator, object()), dsn=ADMIN_DSN)
    return TestClient(app).get("/metrics").text


def _disposables() -> list[str]:
    out = subprocess.run(  # noqa: S603 - fixed command
        ["docker", "ps", "-a", "--filter", "label=org.argos.restore-test", "-q"],  # noqa: S607
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.split()


# The corrupted copy goes first: the development environment ends with the last test passed,
# not with the critical alert on.
def test_a_corrupted_copy_fails_the_test_and_leaves_the_alert(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    _run(repository)
    damaged = tmp_path / "damaged"
    shutil.copytree(repository, damaged)
    for pack in (damaged / "data").rglob("*"):
        if pack.is_file():
            pack.chmod(0o644)  # restic leaves its packs read-only
            data = bytearray(pack.read_bytes())
            data[len(data) // 2] ^= 0xFF
            pack.write_bytes(bytes(data))
    result = _try_again(damaged)
    assert result.result == "failed"
    assert result.reasons
    row = _row(result.snapshot_id, "failed")
    assert row is not None
    assert json.loads(row[3]) if isinstance(row[3], str) else row[3]
    assert "argos_backup_last_restore_test_success 0" in _metrics()
    assert _disposables() == []


def test_a_real_backup_restores_with_its_chains_intact_and_a_dated_row(tmp_path: Path) -> None:
    snapshots, result = _run(tmp_path / "repo")
    assert set(snapshots) == {"db", "evidence", "config"}
    assert result.result == "passed", result.reasons
    assert result.snapshot_id == snapshots["db"]
    assert result.journal_intact and result.journal_entries > 0
    assert result.security_intact
    assert result.counts["graph:inventory"]["restored"] > 0
    assert result.evidence_ok in (True, None)
    row = _row(snapshots["db"], "passed")
    assert row is not None and row[1] is True and row[2] is True
    assert "argos_backup_last_restore_test_success 1" in _metrics()
    assert _disposables() == [], "no disposable database left behind"
    print(f"restore test took {result.duration_seconds:.1f} s")


def test_the_alerts_fire_for_a_failed_test_and_for_a_stale_one() -> None:
    rules = REPO / "deploy" / "dev" / "prometheus" / "rules"
    cases = REPO / "tests" / "backup" / "backup_rules_test.yml"
    done = subprocess.run(  # noqa: S603 - fixed command against a pinned image
        [  # noqa: S607
            "docker", "run", "--rm", "--entrypoint", "promtool",
            "-v", f"{rules}:/rules:ro", "-v", f"{cases}:/cases/backup_rules_test.yml:ro",
            PROMETHEUS, "test", "rules", "/cases/backup_rules_test.yml",
        ],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
