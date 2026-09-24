"""Phase 9 acceptance test (Plan Director §8.2 "Fase 09", ADR-0014 point 10).

What this phase promised, checked on the development environment:

1. The **access battery** is green against the deployed API, and every attempt is in the security
   log, whose chain still verifies.
2. A **complete restore from a copy in a clean environment**: a real backup, a disposable
   PostgreSQL, the chains of the journal and of the security log intact, the counts consistent,
   and the date of the test published in its metric.
3. **An update without a valid signature is refused** (no signature, another key, an image of
   another digest) and no service changes; one with a valid signature whose service never gets
   healthy goes back by itself. Both also coming in through the airlock.
4. **Posture:** no ARGOS container runs as root or with capabilities; every connection to
   PostgreSQL is encrypted; no login role of a service outlives its lease.
5. The **dossier v1** is generated with every evidence it links present.
6. What waits (hardware and the handover of the dossier) is **declared** in the closure report,
   without stopping the tag.
"""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from argos_airgap import Gate
from argos_airgap.importers import update_importer
from argos_api.app import create_app
from argos_auth import JwtValidator
from argos_common import security_log
from argos_common.release import VaultTransitSigner, build_manifest, serialize
from argos_updater import Updater, UpdateRejectedError, verify_bundle
from argos_updater.orchestrator import ComposeOrchestrator
from argos_updater.testing import public_key

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
ADMIN_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
VAULT = "http://127.0.0.1:8200"
SERVICE = "example"
ARGOS_CONTAINERS = ("api", "webhook-worker", "challenge-worker", "evidence-worker",
                    "evidence-api", "verifier", "ai-gateway", "example")  # fmt: skip


def _pytest(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the suite of the repository, by path
        [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:cacheprovider", "-W", "ignore"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=1800,
    )  # fmt: skip


def _docker(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(  # noqa: S603 - fixed commands against the development environment
        ["docker", *args],  # noqa: S607
        input=stdin, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


# ------------------------------------------------------------------ 1. the access battery


def test_1_the_access_battery_is_green_and_the_security_log_verifies() -> None:
    done = _pytest("tests/security/test_access_battery.py")
    assert done.returncode == 0, done.stdout[-3000:]
    result = security_log.verify_chain(ADMIN_DSN)
    assert result.intact, result.anomalies[:3]
    assert result.verified > 0


# ------------------------------------------------------------------ 2. restore from a copy


def _backup_module(name: str) -> ModuleType:
    folder = REPO / "platform" / "backup"
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_2_a_real_copy_restores_in_a_clean_database_with_its_chains_intact(tmp_path: Path) -> None:
    common = _backup_module("backup_common")
    restore = _backup_module("restore_test")
    backup = _backup_module("backup")
    vault = common.Vault(VAULT, "root")
    user, password, lease = vault.database_credential()
    dsn = common.database_url(user, password, "127.0.0.1", 55432)
    started = time.time()
    try:
        with common.Restic(
            common.docker, str(tmp_path / "repo"), vault.restic_password()
        ) as restic:
            backup.backup(
                restic, common.docker, vault, COMPOSE, backup.EVIDENCE_VOLUME, user, password
            )
            result = restore.restore_test(
                restic, common.docker, restore.PostgresProduction(dsn), restore.IMAGE,
                restore.postgres_recorder(dsn),
            )  # fmt: skip
    finally:
        vault.revoke(lease)
    assert result.result == "passed", result.reasons
    assert result.journal_intact and result.security_intact
    assert result.journal_entries > 0 and result.security_events > 0
    assert (
        restore.compare_counts(
            {t: c["production"] for t, c in result.counts.items()},
            {t: c["restored"] for t, c in result.counts.items()},
        )
        == []
    )
    metrics = TestClient(create_app(cast(JwtValidator, object()), dsn=ADMIN_DSN)).get("/metrics")
    published = next(
        float(line.split()[-1]) for line in metrics.text.splitlines()
        if line.startswith("argos_backup_last_restore_test_timestamp_seconds ")
    )  # fmt: skip
    assert published >= started - 5, "the date of this test is the one the alert reads"
    assert "argos_backup_last_restore_test_success 1" in metrics.text


# ------------------------------------------------------------------ 3. signed updates only


@pytest.fixture
def example() -> Iterator[ComposeOrchestrator]:
    compose = ComposeOrchestrator(COMPOSE)
    original = compose.current_image(SERVICE)
    try:
        yield compose
    finally:
        compose.deploy(SERVICE, original)
        assert compose.healthy(SERVICE, original, 120)


def _image(base: str, version: str, extra: str = "") -> str:
    named = f"argos-example-base:{version}"
    _docker("tag", base, named)
    _docker("build", "-q", "-t", f"argos-example:{version}", "-", stdin=(
        f"FROM {named}\nLABEL org.argos.version={version}\n{extra}\n"
    ))  # fmt: skip
    return _docker("image", "inspect", "-f", "{{.Id}}", f"argos-example:{version}")


def _bundle(root: Path, version: str, signed_id: str, saved_id: str, sign: Any) -> Path:
    bundle = root / f"bundle-{version}"
    (bundle / "images").mkdir(parents=True)
    (bundle / "sbom").mkdir()
    (bundle / "sbom" / "argos-example.cdx.json").write_text("{}", encoding="utf-8")
    (bundle / "sbom" / "argos-example.vulns.json").write_text('{"matches": []}', encoding="utf-8")
    images = [{"ref": f"argos-example:{version}@{signed_id}", "component": "ARG-001"}]
    manifest = serialize(build_manifest(version, images, bundle / "sbom", "2026-09-24T00:00:00Z"))
    (bundle / "release-manifest.json").write_bytes(manifest)
    if sign is not None:
        (bundle / "release-manifest.sig").write_bytes(sign(manifest))
    _docker("save", "-o", str(bundle / "images" / "argos-example.tar"), saved_id)
    return bundle


def _tar(folder: Path, into: Path) -> Path:
    with tarfile.open(into, "w") as tar:
        for path in sorted(folder.rglob("*")):
            tar.add(path, arcname=path.relative_to(folder).as_posix(), recursive=False)
    return into


def test_3_an_update_without_a_valid_signature_changes_nothing_and_a_sick_one_goes_back(
    tmp_path: Path, example: ComposeOrchestrator
) -> None:
    signer = VaultTransitSigner(VAULT, "root")
    key = signer.public_key()
    run = uuid.uuid4().hex[:6]
    base = example.current_image(SERVICE)
    good = _image(base, f"0.9.1-t{run}")
    other = _image(base, f"0.9.2-t{run}", "ENV ARGOS_OTHER=1")
    stranger = Ed25519PrivateKey.generate()

    refused = {
        "no signature": _bundle(tmp_path / "a", f"0.9.1-t{run}", good, good, None),
        "another key": _bundle(tmp_path / "b", f"0.9.1-t{run}", good, good, stranger.sign),
        "another digest": _bundle(tmp_path / "c", f"0.9.1-t{run}", good, other, signer.sign),
    }
    for case, bundle in refused.items():
        with pytest.raises(UpdateRejectedError):
            verify_bundle(bundle, key, "0.9.0")
        assert example.current_image(SERVICE) == base, f"{case}: no service changed"
    assert public_key(stranger) != key

    # Through the airlock: the same verification, and a bundle that does verify is queued.
    state, inbox, queue = (
        tmp_path / "state",
        tmp_path / "update" / "inbox",
        tmp_path / "update" / "queue",
    )
    for folder in (
        state,
        inbox,
        tmp_path / "gate" / "in",
        tmp_path / "gate" / "out",
        tmp_path / "gate" / "work",
    ):
        folder.mkdir(parents=True)
    (state / "version").write_text("0.9.0", encoding="utf-8")
    gate = Gate(
        tmp_path / "gate" / "in", tmp_path / "gate" / "out", tmp_path / "gate" / "work",
        importers={"update": update_importer(inbox, queue, lambda: "0.9.0", key)},
        exporters={}, record=lambda *entry: None,
    )  # fmt: skip
    _tar(refused["no signature"], gate.inbox / f"argos-update-0.9.1-t{run}.tar")
    [unsigned] = gate.scan("user:admin.test")
    assert unsigned.result == "rejected" and example.current_image(SERVICE) == base
    (gate.inbox / f"argos-update-0.9.1-t{run}.tar").unlink()

    sick = _image(base, f"0.9.3-t{run}", 'CMD ["sleep", "3600"]')
    _tar(_bundle(tmp_path / "d", f"0.9.3-t{run}", sick, sick, signer.sign),
         gate.inbox / f"argos-update-0.9.3-t{run}.tar")  # fmt: skip
    [queued] = gate.scan("user:admin.test")
    assert queued.result == "imported", queued.reason
    request = json.loads(next(queue.glob("*.json")).read_text(encoding="utf-8"))
    updater = Updater(
        state_dir=state, public_key=key, orchestrator=example,
        services={"argos-example": [SERVICE]}, record=lambda *step: None, health_timeout=60,
    )  # fmt: skip
    with pytest.raises(UpdateRejectedError, match="rolled back"):
        updater.apply(inbox / request["bundle"])
    assert example.current_image(SERVICE) == base, "back to the version that worked"
    assert updater.installed_version() == "0.9.0"


# ------------------------------------------------------------------ 4. posture


def test_4_no_argos_container_runs_as_root_or_with_capabilities() -> None:
    for service in ARGOS_CONTAINERS:
        container = _docker("compose", "-f", str(COMPOSE), "ps", "-q", service)
        assert container, f"{service} is not running"
        info = json.loads(_docker("inspect", container))[0]
        user = info["Config"]["User"]
        assert user not in ("", "root", "0") and not user.startswith("0:"), (service, user)
        assert info["HostConfig"]["CapDrop"] == ["ALL"], service
        assert not info["HostConfig"]["CapAdd"], service
        assert "no-new-privileges" in " ".join(info["HostConfig"]["SecurityOpt"] or []), service


def test_4_every_connection_to_postgresql_is_encrypted_and_no_lease_outlives_its_ttl() -> None:
    with psycopg.connect(ADMIN_DSN) as conn:
        plain = conn.execute(
            "SELECT a.usename, a.client_addr::text FROM pg_stat_activity a"
            " JOIN pg_stat_ssl s ON s.pid = a.pid"
            " WHERE a.backend_type = 'client backend' AND a.client_addr IS NOT NULL AND NOT s.ssl"
        ).fetchall()
        leases = conn.execute(
            "SELECT rolname, rolvaliduntil FROM pg_roles WHERE rolcanlogin AND rolname LIKE 'v-%'"
        ).fetchall()
    assert plain == [], "a connection without TLS"
    # The services connect per request with the users Vault creates for them (F09-05): what stays
    # visible is those users, each one with its end.
    assert any(name.startswith("v-approle-svc-") for name, _ in leases)
    limit = dt.datetime.now(dt.UTC) + dt.timedelta(hours=72, minutes=5)
    for name, until in leases:
        assert until is not None and until <= limit, f"{name} lives longer than its lease"


# ------------------------------------------------------------------ 5. the dossier


def test_5_the_dossier_is_generated_with_every_evidence_present(tmp_path: Path) -> None:
    checked = _pytest("tests/docs/test_security_dossier.py")
    assert checked.returncode == 0, checked.stdout[-2000:]
    done = subprocess.run(  # noqa: S603 - the tool of the repository
        [sys.executable, "tools/docs_pack.py", "--security", "--label", "fase-09", "--no-pdf",
         "--output", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    [pack] = list(tmp_path.iterdir())
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert {"dossier/ens-medidas.md", "dossier/iso27001-anexo-a.md"} <= set(manifest["files"])
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((pack / name).read_bytes()).hexdigest() == digest, name


# ------------------------------------------------------------------ 6. what waits is declared


def test_6_what_waits_for_hardware_or_the_handover_is_declared() -> None:
    report = (REPO / "docs" / "tecnica" / "fases" / "F09-seguridad.md").read_text(encoding="utf-8")
    for task in ("F09-90", "F09-91", "F09-92", "F09-97"):
        assert task in report, f"{task} is not declared in the closure report"
    interfaces = (REPO / "docs" / "fases" / "interfaces-F09.md").read_text(encoding="utf-8")
    for component in (f"ARG-0{n}" for n in range(81, 91)):
        assert component in interfaces, component
