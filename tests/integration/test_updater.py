"""ARG-086 · the updater against the development compose (F09-10).

A bundle signed with the development release key (Vault transit) raises the version of the example
service; a bundle whose image never becomes healthy goes back by itself to the previous one. The
journal and the security log keep every step. The test leaves the example service as it found it.
"""

import json
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from argos_common.release import VaultTransitSigner, build_manifest, serialize
from argos_updater import Updater, UpdateRejectedError
from argos_updater.cli import recorder
from argos_updater.orchestrator import ComposeOrchestrator

from .conftest import ADMIN_DSN

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
VAULT = "http://127.0.0.1:8200"
SERVICE = "example"


def _docker(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(  # noqa: S603 - fixed commands against the development environment
        ["docker", *args],  # noqa: S607
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _image_from(base: str, tag: str, extra: str = "") -> str:
    """A new image of the example service; `extra` may break it on purpose."""
    # BuildKit resolves FROM by name only: the running image gets a tag of the test first.
    named = f"argos-example-base:{tag.rsplit(':', 1)[1]}"
    _docker("tag", base, named)
    dockerfile = f"FROM {named}\nLABEL org.argos.version={tag.rsplit(':', 1)[1]}\n{extra}\n"
    _docker("build", "-q", "-t", tag, "-", stdin=dockerfile)
    return _docker("image", "inspect", "-f", "{{.Id}}", tag)


def _bundle(root: Path, version: str, image_id: str, signer: VaultTransitSigner) -> Path:
    bundle = root / f"bundle-{version}"
    (bundle / "images").mkdir(parents=True)
    (bundle / "sbom").mkdir()
    (bundle / "sbom" / "argos-example.cdx.json").write_text("{}", encoding="utf-8")
    (bundle / "sbom" / "argos-example.vulns.json").write_text('{"matches": []}', encoding="utf-8")
    images = [{"ref": f"argos-example:{version}@{image_id}", "component": "ARG-001"}]
    manifest = serialize(build_manifest(version, images, bundle / "sbom", "2026-09-24T00:00:00Z"))
    (bundle / "release-manifest.json").write_bytes(manifest)
    (bundle / "release-manifest.sig").write_bytes(signer.sign(manifest))
    _docker("save", "-o", str(bundle / "images" / "argos-example.tar"), image_id)
    return bundle


@pytest.fixture
def orchestrator() -> Iterator[ComposeOrchestrator]:
    compose = ComposeOrchestrator(COMPOSE)
    original = compose.current_image(SERVICE)
    try:
        yield compose
    finally:  # the example service as it was, whatever happened
        compose.deploy(SERVICE, original)
        assert compose.healthy(SERVICE, original, 120)


def _updater(state: Path, orchestrator: ComposeOrchestrator, signer: VaultTransitSigner) -> Updater:
    return Updater(
        state_dir=state,
        public_key=signer.public_key(),
        orchestrator=orchestrator,
        services={"argos-example": [SERVICE]},
        record=recorder(ADMIN_DSN),
        health_timeout=60,
    )


def test_a_good_bundle_updates_and_a_sick_one_goes_back_alone(
    tmp_path: Path, orchestrator: ComposeOrchestrator
) -> None:
    signer = VaultTransitSigner(VAULT, "root")
    run = uuid.uuid4().hex[:6]
    state = tmp_path / "state"
    state.mkdir()
    (state / "version").write_text("0.9.0", encoding="utf-8")
    with psycopg.connect(ADMIN_DSN) as conn:
        journal_from = conn.execute(
            "SELECT coalesce(max(seq), 0) FROM argos.audit_journal"
        ).fetchone()
        security_from = conn.execute("SELECT coalesce(max(seq), 0) FROM security.events").fetchone()
    base = orchestrator.current_image(SERVICE)

    good = _image_from(base, f"argos-example:0.9.1-t{run}")
    updater = _updater(state, orchestrator, signer)
    assert updater.apply(_bundle(tmp_path, f"0.9.1-t{run}", good, signer)) == f"0.9.1-t{run}"
    assert orchestrator.current_image(SERVICE) == good

    sick = _image_from(base, f"argos-example:0.9.2-t{run}", 'CMD ["sleep", "3600"]')
    with pytest.raises(UpdateRejectedError, match="rolled back"):
        updater.apply(_bundle(tmp_path, f"0.9.2-t{run}", sick, signer))
    assert orchestrator.current_image(SERVICE) == good, "back to the version that worked"
    assert orchestrator.healthy(SERVICE, good, 120)
    assert updater.installed_version() == f"0.9.1-t{run}"
    assert not (state / "plan.json").exists()

    assert journal_from is not None and security_from is not None
    with psycopg.connect(ADMIN_DSN) as conn:
        journal = conn.execute(
            "SELECT action FROM argos.audit_journal WHERE seq > %s AND actor = 'system:updater'",
            journal_from,
        ).fetchall()
        security = conn.execute(
            "SELECT kind, outcome FROM security.events WHERE seq > %s AND actor = 'system:updater'",
            security_from,
        ).fetchall()
    actions = {row[0] for row in journal}
    assert {"update.verified", "update.applied", "update.rolled_back"} <= actions
    assert ("update.rolled_back", "failed") in {(k, o) for k, o in security}
    print(json.dumps(sorted(actions)))
