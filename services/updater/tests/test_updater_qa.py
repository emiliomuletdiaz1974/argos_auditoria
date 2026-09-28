"""QA-20 · the updater only ever loads what was signed, and a failure midway leaves a way back.

Findings of the quality review (docs/calidad/revision-qa-f01-f10.md):
- QA-073: an archive the manifest does not list, or a signed image whose tags were changed to name
  another service, must not reach `docker load`;
- QA-074: a deploy that fails inside the orchestrator is undone too, and the reverse plan stays on
  disk when the way back itself fails;
- QA-084: the watcher survives a request it cannot read and keeps it for the operator.
"""

import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from argos_updater import PLAN, Updater, UpdateRejectedError
from argos_updater.testing import image_archive, public_key, signed_bundle

KEY = Ed25519PrivateKey.generate()
SERVICES = {"argos-api": ["api", "webhook-worker"], "argos-example": ["example"]}


class Orchestrator:
    def __init__(self, fail_deploy: str | None = None, fail_undo: bool = False) -> None:
        self.loaded: list[str] = []
        self.running = {s: "old-" + s for names in SERVICES.values() for s in names}
        self._fail_deploy = fail_deploy
        self._fail_undo = fail_undo

    def load_images(self, archives: list[Path]) -> None:
        self.loaded = sorted(p.name for p in archives)

    def current_image(self, service: str) -> str:
        return self.running[service]

    def deploy(self, service: str, image: str) -> None:
        going_back = image.startswith("old-")
        if going_back and self._fail_undo:
            raise RuntimeError("the orchestrator is down")
        self.running[service] = image  # the tag moved before the failure
        if service == self._fail_deploy and not going_back:
            raise RuntimeError("compose up failed")

    def healthy(self, service: str, image: str, timeout: float) -> bool:
        return True


def _updater(tmp_path: Path, orchestrator: Orchestrator) -> Updater:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "version").write_text("0.1.0", encoding="utf-8")
    events: list[tuple[str, str, Mapping[str, Any]]] = []
    return Updater(
        state_dir=state,
        public_key=public_key(KEY),
        orchestrator=orchestrator,
        services=SERVICES,
        record=lambda kind, outcome, detail: events.append((kind, outcome, detail)),
        health_timeout=0,
    )


def _retag(archive: Path, tag: str) -> None:
    """Change the tags of a classic archive, keeping its configuration (and so its id)."""
    with tarfile.open(archive) as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    index = json.loads(members["manifest.json"])
    index[0]["RepoTags"] = [tag]
    members["manifest.json"] = json.dumps(index).encode()
    with tarfile.open(archive, "w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


# --- QA-073: only what was signed is loaded --------------------------------------------------


def test_an_archive_the_manifest_does_not_list_is_refused_untouched(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path, "0.2.0", KEY, list(SERVICES))
    image_archive(bundle / "images" / "evil.tar", "argos-evidence", "0.2.0")
    orchestrator = Orchestrator()
    with pytest.raises(UpdateRejectedError, match="evil.tar"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.loaded == []


def test_a_signed_image_retagged_as_another_service_is_refused(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path, "0.2.0", KEY, list(SERVICES))
    _retag(bundle / "images" / "argos-example.tar", "argos-evidence:dev")
    orchestrator = Orchestrator()
    with pytest.raises(UpdateRejectedError, match="argos-evidence"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.loaded == []


def test_only_the_signed_archives_are_loaded(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path, "0.2.0", KEY, list(SERVICES))
    orchestrator = Orchestrator()
    _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.loaded == ["argos-api.tar", "argos-example.tar"]


# --- QA-074: a failure inside a deploy is undone, and the plan survives a failed way back -----


def test_a_deploy_that_fails_inside_the_orchestrator_is_undone(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path, "0.2.0", KEY, list(SERVICES))
    orchestrator = Orchestrator(fail_deploy="webhook-worker")
    updater = _updater(tmp_path, orchestrator)
    with pytest.raises(UpdateRejectedError):
        updater.apply(bundle)
    assert orchestrator.running == {
        "api": "old-api", "webhook-worker": "old-webhook-worker", "example": "old-example"
    }  # fmt: skip


def test_when_the_way_back_fails_the_plan_stays_for_recover(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path, "0.2.0", KEY, list(SERVICES))
    orchestrator = Orchestrator(fail_deploy="webhook-worker", fail_undo=True)
    updater = _updater(tmp_path, orchestrator)
    with pytest.raises(UpdateRejectedError):
        updater.apply(bundle)
    assert (tmp_path / "state" / PLAN).is_file(), "recover() needs the plan to put things back"


# --- QA-084: the watcher survives what it cannot read -------------------------------------


def test_the_watcher_keeps_a_request_it_cannot_read_and_goes_on(tmp_path: Path) -> None:
    from argos_updater.cli import watch_once

    inbox, queue = tmp_path / "inbox", tmp_path / "queue"
    inbox.mkdir()
    queue.mkdir()
    (queue / "1-broken.json").write_text("{not json", encoding="utf-8")
    (queue / "2-nobundle.json").write_text("{}", encoding="utf-8")
    bundle = signed_bundle(inbox, "0.2.0", KEY, list(SERVICES))
    (queue / "3-good.json").write_text(json.dumps({"bundle": bundle.name}), encoding="utf-8")
    orchestrator = Orchestrator()
    watch_once(_updater(tmp_path, orchestrator), inbox, queue)
    assert orchestrator.running["api"] != "old-api", "the good request after the bad ones ran"
    kept = sorted(p.name for p in queue.iterdir())
    assert kept == ["1-broken.json.failed", "2-nobundle.json.failed"]
