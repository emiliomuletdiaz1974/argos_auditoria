"""Phase 10 acceptance test (Plan Director §8.2 "Fase 10", ADR-0015).

What this phase promised, checked on the development environment:

1. **ARGOS verifies ARGOS:** the self-check of the candidate ends with a signed dossier, no
   serious finding and the trap present; with the journal broken in a disposable database, the
   gate blocks the release.
2. **Alerts:** the critical ones (journal, WORM, disk and restore) exist, each with its runbook;
   each fires on its cause (promtool series and a broken journal read by the health service), and
   an alert of Alertmanager reaches the API with its runbook for the console.
3. **A timed drill** of two runbooks drawn by lot, recorded in the journal (`tools/drill.py`).
4. **Installer:** a complete run with doubles of the hardware produces the signed report (signed
   by Vault transit); the check of the room gives its verdict on the reference outputs.
5. **Limits of the size:** an S refuses its 41st system with the honest message.
6. **Size M:** the assisted failover promotes the replica with the journal intact.
7. **What waits is declared:** F10-90, F10-91, F10-92, F10-97 and the pilot, in the closure report.
"""

import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from psycopg import sql

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator
from argos_common.capacity import limits_of
from argos_common.migrations import apply_migrations
from argos_common.release import VaultTransitSigner, verify_signature
from argos_installer import ORDER, Completed, InstallConfig, Installer

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
ADMIN_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
MIGRATIONS_DIR = REPO / "services" / "api" / "migrations"
VAULT = "http://127.0.0.1:8200"
SIZES = REPO / "platform" / "operation" / "sizes.yaml"
SITE = REPO / "tests" / "fixtures" / "site"


def _pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the suite of the repository, by path
        [sys.executable, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider", "-W", "ignore"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=1800,
    )  # fmt: skip


@pytest.fixture
def migrated_db() -> Iterator[str]:
    """A database of its own for this test, migrated: the phase test touches nobody else's data."""
    name = f"argos_phase10_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
    try:
        apply_migrations(dsn, MIGRATIONS_DIR)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


# ------------------------------------------------------------------ 1. ARGOS verifies ARGOS


def test_1_the_self_check_passes_with_the_trap_and_a_broken_journal_blocks_it() -> None:
    done = _pytest("tests/integration/test_selfcheck.py", "tests/integration/test_self_facts.py")
    assert done.returncode == 0, done.stdout[-3000:]


# ------------------------------------------------------------------ 2. alerts


def _rules() -> dict[str, dict[str, object]]:
    rules: dict[str, dict[str, object]] = {}
    files = [REPO / "platform" / "observability" / "rules" / "argos.rules.yml",
             *(REPO / "deploy" / "dev" / "prometheus" / "rules").glob("*.yml")]  # fmt: skip
    for path in files:
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            for rule in group["rules"]:
                if "alert" in rule:
                    rules[rule["alert"]] = rule
    return rules


def test_2_the_critical_alerts_fire_on_their_cause_and_reach_the_console() -> None:
    rules = _rules()
    for name in ("JournalNotIntact", "WormWriteFailing", "EvidenceDisk85",
                 "BackupRestoreTestFailed"):  # fmt: skip
        assert rules[name]["labels"]["severity"] == "critical", name  # type: ignore[index]
    for name, rule in rules.items():
        runbook = rule.get("annotations", {}).get("runbook_url")  # type: ignore[attr-defined]
        if runbook:
            assert (REPO / runbook).is_file(), (name, runbook)
    done = _pytest(
        "tests/observability/test_alert_rules_promtool.py",
        "tests/observability/test_operation_alerts_delivery.py",
        "tests/integration/test_health.py",
        "tests/integration/test_operation_alerts.py",
    )
    assert done.returncode == 0, done.stdout[-3000:]


# ------------------------------------------------------------------ 3. the drill


def test_3_a_timed_drill_of_two_runbooks_is_in_the_journal() -> None:
    done = subprocess.run(  # noqa: S603 - the tool of the repository
        [sys.executable, "tools/drill.py", "--operator", "fase10", "--seed", "10"],
        cwd=REPO, input="\n" * 10, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "ARGOS_DRILL_DSN": ADMIN_DSN}, timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    seq = int(re.search(r"asiento (\d+) del diario", done.stdout)[1])  # type: ignore[index]
    with psycopg.connect(ADMIN_DSN) as conn:
        action, payload = conn.execute(
            "SELECT action, payload_canon FROM argos.audit_journal WHERE seq = %s", (seq,)
        ).fetchone()  # type: ignore[misc]
    drill = json.loads(payload)
    assert action == "ops.drill"
    assert len(drill["runbooks"]) == 2 and drill["passed"] is True
    assert isinstance(drill["seconds"], int)


# ------------------------------------------------------------------ 4. the installer


class Hardware:
    """Doubles of every command of week 1, with the reference outputs of the room."""

    outputs = {
        "timedatectl": "yes",
        "cryptsetup": "Tokens:\n  0: systemd-tpm2",
        "kcadm.sh get": '[ {\n  "username" : "admin.organismo",\n'
        '  "requiredActions" : [ "CONFIGURE_TOTP", "UPDATE_PASSWORD" ]\n} ]',
        "kcadm.sh get-roles": '[ {\n  "name" : "platform_admin"\n} ]',
        "ipmitool": (SITE / "ipmitool_sensor_list.txt").read_text(encoding="utf-8"),
        "ethtool": (SITE / "ethtool_10g.txt").read_text(encoding="utf-8"),
        "ping": (SITE / "ping_ok.txt").read_text(encoding="utf-8"),
        "nvidia-smi": (SITE / "nvidia_smi_l40s.txt").read_text(encoding="utf-8"),
    }

    def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
        return Completed(0, self.outputs.get(" ".join(args[:2]), self.outputs.get(args[0], "")))


def _config(size: str) -> InstallConfig:
    config = yaml.safe_load(
        (REPO / "platform" / "operation" / "installer.example.yaml").read_text(encoding="utf-8")
    )
    config["site"] = {**config["site"], "size": size, "limits_file": str(SIZES)}
    return InstallConfig.model_validate(config)


def test_4_a_complete_installation_gives_a_signed_report_and_the_verdict_of_the_room(
    tmp_path: Path,
) -> None:
    signer = VaultTransitSigner(VAULT, "root")
    entries: list[tuple[object, ...]] = []
    report = Installer(
        _config("S"), Hardware(), state_dir=tmp_path, signer=signer,
        record=lambda *entry: entries.append(entry),
    ).run()  # fmt: skip
    assert report["completed"], report["steps"]
    assert [step["key"] for step in report["steps"]] == list(ORDER)
    [site] = [step for step in report["steps"] if step["key"] == "site"]
    assert site["detail"].startswith("sala fit para la talla S")
    body = (tmp_path / "installation-report.json").read_bytes()
    verify_signature(body, (tmp_path / "installation-report.json.sig").read_bytes(),
                     signer.public_key())  # fmt: skip
    assert entries and entries[-1][1] == "install.completed"

    # The same room does not give an M: the installation stops there and says why.
    stopped = Installer(
        _config("M"), Hardware(), state_dir=tmp_path / "m", signer=signer,
        record=lambda *entry: None,
    ).run()  # fmt: skip
    assert not stopped["completed"]
    assert stopped["steps"][-1]["key"] == "site"
    assert "data_link unfit" in stopped["steps"][-1]["detail"]


# ------------------------------------------------------------------ 5. limits of the size


class Tokens:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub=token, name=token, roles=frozenset({token}), amr=frozenset({"pwd", "otp"})
        )


def test_5_an_s_refuses_its_41st_system_with_the_honest_message(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        for n in range(40):
            conn.execute(
                "INSERT INTO argos.systems (id, name, kind, connection) VALUES (%s, %s, 'rdbms',"
                " '{}')",
                (str(uuid.uuid4()), f"system-{n}"),
            )
    app = create_app(cast(JwtValidator, Tokens()), dsn=migrated_db,
                     size_limits=("S", limits_of(SIZES, "S")))  # fmt: skip
    refused = TestClient(app).post(
        f"{API_PREFIX}/systems",
        json={"name": "system-41", "kind": "rdbms", "environment": "production",
              "connector": "argos_sql.postgres:PostgresConnector",
              "config": {"statement_timeout_ms": 5000}},
        headers={"Authorization": "Bearer platform_admin"},
    )  # fmt: skip
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "La talla S admite 40" in detail and "ampliar la talla" in detail


# ------------------------------------------------------------------ 6. size M


def test_6_the_assisted_failover_promotes_the_replica_with_the_journal_intact() -> None:
    done = _pytest("tests/integration/test_ha_size_m.py")
    assert done.returncode == 0, done.stdout[-3000:]


# ------------------------------------------------------------------ 7. what waits is declared


def test_7_what_waits_for_hardware_or_a_decision_is_declared() -> None:
    report = (REPO / "docs" / "tecnica" / "fases" / "F10-operacion.md").read_text(encoding="utf-8")
    for task in ("F10-90", "F10-91", "F10-92", "F10-97", "P-01"):
        assert task in report, f"{task} is not declared in the closure report"
    interfaces = (REPO / "docs" / "fases" / "interfaces-F10.md").read_text(encoding="utf-8")
    for component in (f"ARG-{n:03d}" for n in range(91, 101)):
        assert component in interfaces, component
