"""ARG-086 · the transactional updater, with a fake orchestrator (F09-10).

Nothing is touched before everything verifies: a bundle without a signature, signed with another
key, with its manifest changed or with an image that is not the one signed is refused without a
single call to the orchestrator. A step that fails undoes what was done, in reverse order. A process
that dies in the middle leaves its reverse plan on disk, and `recover()` puts back the previous
version. An older version is refused unless the downgrade is explicit.
"""

import hashlib
import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.release import build_manifest, serialize
from argos_updater import Updater, UpdateRejectedError

KEY = Ed25519PrivateKey.generate()
OTHER = Ed25519PrivateKey.generate()
SERVICES = {"argos-example": ["example"], "argos-api": ["api", "webhook-worker"]}


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _image_tar(path: Path, name: str, version: str) -> str:
    """A `docker save` archive with one image; returns its id (the digest of its config)."""
    config = json.dumps({"config": {"Labels": {"org.argos.version": version}}, "name": name})
    config_bytes = config.encode()
    digest = hashlib.sha256(config_bytes).hexdigest()
    manifest = json.dumps([{"Config": f"blobs/sha256/{digest}", "RepoTags": [f"{name}:{version}"]}])
    with tarfile.open(path, "w") as tar:
        for member, data in (
            ("manifest.json", manifest.encode()),
            (f"blobs/sha256/{digest}", config_bytes),
        ):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return f"sha256:{digest}"


def _bundle(root: Path, version: str, key: Ed25519PrivateKey = KEY) -> Path:
    bundle = root / f"bundle-{version}"
    (bundle / "images").mkdir(parents=True)
    (bundle / "sbom").mkdir()
    images = []
    for name in SERVICES:
        digest = _image_tar(bundle / "images" / f"{name}.tar", name, version)
        images.append({"ref": f"{name}:{version}@{digest}", "component": "ARG-000"})
        (bundle / "sbom" / f"{name}.cdx.json").write_text("{}", encoding="utf-8")
        (bundle / "sbom" / f"{name}.vulns.json").write_text('{"matches": []}', encoding="utf-8")
    manifest = serialize(build_manifest(version, images, bundle / "sbom", "2026-09-23T00:00:00Z"))
    (bundle / "release-manifest.json").write_bytes(manifest)
    (bundle / "release-manifest.sig").write_bytes(key.sign(manifest))
    return bundle


class FakeOrchestrator:
    def __init__(self, healthy: bool = True, crash_on: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.running = {s: "sha256:old-" + s for names in SERVICES.values() for s in names}
        self._healthy = healthy
        self._crash_on = crash_on

    def load_images(self, archives: list[Path]) -> None:
        self.calls.append(("load", *sorted(p.name for p in archives)))

    def current_image(self, service: str) -> str:
        return self.running[service]

    def deploy(self, service: str, image: str) -> None:
        if service == self._crash_on and not image.startswith("sha256:old-"):
            raise Crash(service)
        self.calls.append(("deploy", service, image))
        self.running[service] = image

    def healthy(self, service: str, image: str, timeout: float) -> bool:
        return self._healthy


class Crash(BaseException):  # noqa: N818 - the process dies, it is not an error it handles
    """The updater process killed in the middle of a step."""


def _updater(tmp_path: Path, orchestrator: FakeOrchestrator, installed: str = "0.1.0") -> Updater:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "version").write_text(installed, encoding="utf-8")
    events: list[tuple[str, str, Mapping[str, Any]]] = []
    updater = Updater(
        state_dir=state,
        public_key=_public(KEY),
        orchestrator=orchestrator,
        services=SERVICES,
        record=lambda kind, outcome, detail: events.append((kind, outcome, detail)),
        health_timeout=0,
    )
    updater.events = events  # type: ignore[attr-defined]
    return updater


# --- nothing is touched before everything verifies ------------------------------------------


def test_a_bundle_without_a_signature_is_refused_untouched(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0")
    (bundle / "release-manifest.sig").unlink()
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="signature"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


def test_a_bundle_signed_with_another_key_is_refused_untouched(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0", key=OTHER)
    # the key that travels in the bundle proves nothing: only the pinned one counts
    (bundle / "release.pub").write_bytes(_public(OTHER))
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="signature"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


def test_a_changed_manifest_is_refused_untouched(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0")
    manifest = bundle / "release-manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b"0.2.0", b"0.2.1"))
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


def test_an_image_that_is_not_the_signed_one_is_refused_untouched(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0")
    _image_tar(bundle / "images" / "argos-api.tar", "argos-api", "9.9.9")
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="argos-api"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


def test_a_changed_sbom_is_refused_untouched(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0")
    (bundle / "sbom" / "argos-api.vulns.json").write_text('{"matches": ["x"]}', encoding="utf-8")
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="vulns"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


@pytest.mark.parametrize("version", ["0.1.0", "0.0.9"])
def test_the_same_or_an_older_version_is_refused(tmp_path: Path, version: str) -> None:
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="older"):
        _updater(tmp_path, orchestrator).apply(_bundle(tmp_path, version))
    assert orchestrator.calls == []


def test_an_explicit_downgrade_is_allowed_and_recorded(tmp_path: Path) -> None:
    updater = _updater(tmp_path, FakeOrchestrator())
    updater.apply(_bundle(tmp_path, "0.0.9"), allow_downgrade=True)
    assert updater.installed_version() == "0.0.9"
    assert ("update.downgrade", "allowed") in [(k, o) for k, o, _ in updater.events]  # type: ignore[attr-defined]


def test_a_version_that_is_not_a_version_is_refused(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, "0.2.0;rm")
    orchestrator = FakeOrchestrator()
    with pytest.raises(UpdateRejectedError, match="version"):
        _updater(tmp_path, orchestrator).apply(bundle)
    assert orchestrator.calls == []


# --- the transaction ----------------------------------------------------------------------


def test_a_good_update_moves_every_service_and_records_it(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator()
    updater = _updater(tmp_path, orchestrator)
    updater.apply(_bundle(tmp_path, "0.2.0"))
    assert updater.installed_version() == "0.2.0"
    deployed = [c[1] for c in orchestrator.calls if c[0] == "deploy"]
    assert deployed == ["api", "webhook-worker", "example"]
    assert not (tmp_path / "state" / "plan.json").exists()
    kinds = [(k, o) for k, o, _ in updater.events]  # type: ignore[attr-defined]
    assert ("update.applied", "succeeded") in kinds


def test_a_step_that_does_not_verify_is_undone_in_reverse(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator(healthy=False)
    updater = _updater(tmp_path, orchestrator)
    with pytest.raises(UpdateRejectedError, match="rolled back"):
        updater.apply(_bundle(tmp_path, "0.2.0"))
    assert updater.installed_version() == "0.1.0"
    deploys = [c for c in orchestrator.calls if c[0] == "deploy"]
    # api is deployed, fails its health, and goes back to what it was
    assert deploys == [("deploy", "api", deploys[0][2]), ("deploy", "api", "sha256:old-api")]
    assert orchestrator.running["api"] == "sha256:old-api"
    assert not (tmp_path / "state" / "plan.json").exists()
    assert ("update.rolled_back", "failed") in [
        (k, o)
        for k, o, _ in updater.events  # type: ignore[attr-defined]
    ]


def test_a_process_killed_midway_is_recovered_to_the_previous_version(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator(crash_on="example")
    updater = _updater(tmp_path, orchestrator)
    with pytest.raises(Crash):
        updater.apply(_bundle(tmp_path, "0.2.0"))
    assert (tmp_path / "state" / "plan.json").exists(), "the reverse plan was on disk before"

    restarted = _updater(tmp_path, FakeOrchestrator())
    restarted._orchestrator.running.update(orchestrator.running)  # type: ignore[attr-defined]
    assert restarted.recover() is True
    assert restarted.installed_version() == "0.1.0"
    running = restarted._orchestrator.running  # type: ignore[attr-defined]
    assert running["api"] == "sha256:old-api"
    assert running["webhook-worker"] == "sha256:old-webhook-worker"
    assert not (tmp_path / "state" / "plan.json").exists()


def test_recover_without_a_plan_does_nothing(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator()
    assert _updater(tmp_path, orchestrator).recover() is False
    assert orchestrator.calls == []


def _oci_tar(path: Path, tamper: bool = False) -> str:
    """An OCI layout, as `docker save` writes it with the containerd image store."""
    blob = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json"}).encode()
    digest = hashlib.sha256(blob).hexdigest()
    index = json.dumps({"manifests": [{"digest": f"sha256:{digest}"}]}).encode()
    with tarfile.open(path, "w") as tar:
        for member, data in (
            ("index.json", index),
            (f"blobs/sha256/{digest}", blob + (b" " if tamper else b"")),
        ):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return f"sha256:{digest}"


def test_an_oci_archive_is_identified_by_the_digest_of_its_index(tmp_path: Path) -> None:
    from argos_updater import _image_id

    archive = tmp_path / "oci.tar"
    digest = _oci_tar(archive)
    assert _image_id(archive) == digest


def test_an_oci_archive_with_a_changed_blob_is_refused(tmp_path: Path) -> None:
    from argos_updater import _image_id

    archive = tmp_path / "oci.tar"
    _oci_tar(archive, tamper=True)
    with pytest.raises(UpdateRejectedError, match="blob"):
        _image_id(archive)
