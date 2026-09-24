"""ARG-086 · the transactional signed updater (F09-10, ADR-0014, deviation note ARG-086).

An update is completed entirely or leaves the system exactly at the version it had:

1. **Verify everything first** (`verify_bundle`): the Ed25519 signature of the manifest against the
   public key pinned on the appliance (never a key that travels in the bundle), the version against
   a strict pattern and against the installed one (no going back unless explicit), the digest of
   every image archive, the hashes of the SBOMs and vulnerability reports and, if the bundle
   carries normative content, its own signature (ARG-040). Nothing is touched before that.
2. **Write the reverse plan to disk** before the first step.
3. **Apply by steps** (`Step`: do, undo, verify): images, migrations (expand-contract, so going back
   in code never needs going back in data), each service with its health watched, content.
4. **On failure**, undo what was done in reverse order. If the process dies, `recover()` finds the
   plan at the next start and completes the way back.

Every step goes to the journal and to the security log through `record`.
"""

import hashlib
import json
import re
import tarfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from argos_common.errors import IntegrityError
from argos_common.release import serialize, verify_release_files, verify_signature

VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.]*)?$")
MANIFEST = "release-manifest.json"
SIGNATURE = "release-manifest.sig"
PLAN = "plan.json"
INSTALLED = "version"

Record = Callable[[str, str, Mapping[str, Any]], None]


class UpdateRejectedError(Exception):
    """The update was not applied; the system is at the version it had."""


class Orchestrator(Protocol):
    def load_images(self, archives: list[Path]) -> None: ...
    def current_image(self, service: str) -> str: ...
    def deploy(self, service: str, image: str) -> None: ...
    def healthy(self, service: str, image: str, timeout: float) -> bool: ...


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    do: Callable[[], None]
    undo: Callable[[], None]
    verify: Callable[[], bool]


@dataclass(frozen=True, slots=True)
class VerifiedBundle:
    path: Path
    manifest: dict[str, Any]
    images: dict[str, str] = field(default_factory=dict)  # image name -> id (sha256:…)

    @property
    def version(self) -> str:
        return str(self.manifest["version"])


def _order(version: str) -> tuple[int, int, int, int, str]:
    core, _, pre = version.partition("-")
    major, minor, patch = (int(p) for p in core.split("."))
    return major, minor, patch, 0 if pre else 1, pre  # a pre-release comes before its release


def _image_id(archive: Path) -> str:
    """The id of the one image in a `docker save` archive, checked against its content.

    With the containerd image store the archive is an OCI layout: the id is the digest in
    `index.json`, and every blob must hash to the digest it is named after. With the classic store
    the id is the digest of the image configuration.
    """
    try:
        with tarfile.open(archive) as tar:
            names = set(tar.getnames())
            if "index.json" in names:
                return _oci_image_id(tar, archive.name)
            index = json.loads(_member(tar, "manifest.json"))
            if not isinstance(index, list) or len(index) != 1:
                raise UpdateRejectedError(f"{archive.name} must hold exactly one image")
            config = _member(tar, str(index[0]["Config"]))
    except (tarfile.TarError, OSError, KeyError, ValueError) as broken:
        raise UpdateRejectedError(f"{archive.name} is not a readable image archive") from broken
    return "sha256:" + hashlib.sha256(config).hexdigest()


def _oci_image_id(tar: tarfile.TarFile, name: str) -> str:
    manifests = json.loads(_member(tar, "index.json")).get("manifests") or []
    if len(manifests) != 1:
        raise UpdateRejectedError(f"{name} must hold exactly one image")
    for member in tar.getmembers():
        if member.isfile() and member.name.startswith("blobs/sha256/"):
            expected = member.name.rsplit("/", 1)[1]
            extracted = tar.extractfile(member)
            digest = hashlib.sha256()
            while extracted is not None and (chunk := extracted.read(1 << 20)):
                digest.update(chunk)
            if digest.hexdigest() != expected:
                raise UpdateRejectedError(f"{name}: a blob is not what its digest says")
    top = str(manifests[0]["digest"])
    if f"blobs/sha256/{top.split(':', 1)[1]}" not in tar.getnames():
        raise UpdateRejectedError(f"{name}: the image it names is not in it")
    return top


def _member(tar: tarfile.TarFile, name: str) -> bytes:
    extracted = tar.extractfile(name)
    if extracted is None:
        raise KeyError(name)
    return extracted.read()


def _image_name(ref: str) -> str:
    return ref.split("@", 1)[0].rsplit(":", 1)[0].rsplit("/", 1)[-1]


def verify_bundle(
    bundle: Path,
    public_key: bytes,
    installed: str | None,
    allow_downgrade: bool = False,
    content_key: bytes | None = None,
) -> VerifiedBundle:
    """Everything the update will use, checked before anything is touched."""
    raw, signature = bundle / MANIFEST, bundle / SIGNATURE
    if not raw.is_file() or not signature.is_file():
        raise UpdateRejectedError("the bundle has no signed manifest (manifest and signature)")
    data = raw.read_bytes()
    try:
        verify_signature(data, signature.read_bytes(), public_key)
    except IntegrityError:
        raise UpdateRejectedError(
            "the signature of the manifest is not the release key's"
        ) from None
    manifest: dict[str, Any] = json.loads(data)
    if serialize(manifest) != data:
        raise UpdateRejectedError("the manifest is not in canonical form")
    version = str(manifest.get("version", ""))
    if not VERSION.match(version):
        raise UpdateRejectedError(f"the version of the manifest is not a version: {version!r}")
    if installed and _order(version) <= _order(installed) and not allow_downgrade:
        raise UpdateRejectedError(
            f"{version} is not newer than the installed {installed}: older or equal, refused"
        )
    images: dict[str, str] = {}
    for image in manifest.get("images", []):
        name = _image_name(str(image["ref"]))
        signed = str(image["ref"]).split("@", 1)[1]
        archive = bundle / "images" / f"{name}.tar"
        if not archive.is_file() or _image_id(archive) != signed:
            raise UpdateRejectedError(f"the image {name} is not the one the manifest signed")
        images[name] = signed
    try:
        verify_release_files(manifest, bundle / "sbom")
    except IntegrityError as changed:
        raise UpdateRejectedError(str(changed)) from None
    content = bundle / "content"
    if content.is_dir():
        if content_key is None:
            raise UpdateRejectedError("the bundle carries content but no content key is pinned")
        from argos_ontology.bundle import BundleRejectedError
        from argos_ontology.bundle import verify_bundle as verify_content

        try:
            verify_content(
                (content / "ontology.tar.gz").read_bytes(),
                (content / "ontology.sig").read_bytes(),
                content_key,
            )
        except (BundleRejectedError, OSError) as refused:
            raise UpdateRejectedError(
                f"the content of the bundle does not verify: {refused}"
            ) from None
    return VerifiedBundle(bundle, manifest, images)


class Updater:
    def __init__(
        self,
        *,
        state_dir: Path,
        public_key: bytes,
        orchestrator: Orchestrator,
        services: Mapping[str, list[str]],
        record: Record,
        health_timeout: float = 120.0,
        migrate: Callable[[Path], None] | None = None,
        load_content: Callable[[Path], None] | None = None,
        content_key: bytes | None = None,
    ) -> None:
        self._state = state_dir
        self._public_key = public_key
        self._orchestrator = orchestrator
        self._services = services
        self._record = record
        self._health_timeout = health_timeout
        self._migrate = migrate
        self._load_content = load_content
        self._content_key = content_key

    # --- state ----------------------------------------------------------------------------

    def installed_version(self) -> str | None:
        path = self._state / INSTALLED
        return path.read_text(encoding="utf-8").strip() if path.is_file() else None

    def _write(self, name: str, text: str) -> None:
        temporary = self._state / f".{name}.tmp"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self._state / name)

    def _plan(self) -> dict[str, Any] | None:
        path = self._state / PLAN
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _save_plan(self, plan: dict[str, Any]) -> None:
        self._write(PLAN, json.dumps(plan, indent=1))

    # --- the transaction ------------------------------------------------------------------

    def verify(self, bundle: Path, allow_downgrade: bool = False) -> VerifiedBundle:
        try:
            verified = verify_bundle(
                bundle,
                self._public_key,
                self.installed_version(),
                allow_downgrade,
                self._content_key,
            )
        except UpdateRejectedError as refused:
            self._record(
                "update.rejected", "refused", {"bundle": bundle.name, "reason": str(refused)[:200]}
            )
            raise
        self._record("update.verified", "succeeded", {"version": verified.version})
        return verified

    def _steps(self, verified: VerifiedBundle, plan: dict[str, Any]) -> list[Step]:
        bundle = verified.path
        archives = sorted((bundle / "images").glob("*.tar"))
        steps = [
            Step(
                "images",
                do=lambda: self._orchestrator.load_images(archives),
                undo=lambda: None,  # images that are not running harm nothing
                verify=lambda: True,
            )
        ]
        migrations = bundle / "migrations"
        if migrations.is_dir() and self._migrate is not None:
            migrate = self._migrate
            steps.append(
                Step("migrations", lambda: migrate(migrations), lambda: None, lambda: True)
            )  # expand-contract: the previous code still runs on the new schema
        for name in sorted(verified.images):
            for service in self._services.get(name, []):
                steps.append(self._deploy_step(service, verified.images[name], plan))
        content = bundle / "content"
        if content.is_dir() and self._load_content is not None:
            load = self._load_content
            steps.append(Step("content", lambda: load(content), lambda: None, lambda: True))
        return steps

    def _deploy_step(self, service: str, image: str, plan: dict[str, Any]) -> Step:
        def do() -> None:
            previous = self._orchestrator.current_image(service)
            # the way back is on disk before the service changes
            plan["done"].append(
                {"step": f"deploy:{service}", "service": service, "previous": previous}
            )
            self._save_plan(plan)
            self._orchestrator.deploy(service, image)

        def undo() -> None:
            previous = next(d["previous"] for d in plan["done"] if d.get("service") == service)
            self._orchestrator.deploy(service, previous)

        return Step(
            f"deploy:{service}",
            do,
            undo,
            lambda: self._orchestrator.healthy(service, image, self._health_timeout),
        )

    def apply(self, bundle: Path, allow_downgrade: bool = False) -> str:
        if self._plan() is not None:
            raise UpdateRejectedError("an interrupted update is pending: run recover first")
        verified = self.verify(bundle, allow_downgrade)
        installed = self.installed_version()
        if allow_downgrade and installed and _order(verified.version) <= _order(installed):
            self._record("update.downgrade", "allowed", {"from": installed, "to": verified.version})
        plan: dict[str, Any] = {"from": installed, "to": verified.version, "done": []}
        self._save_plan(plan)  # the reverse plan exists before the first step
        done: list[Step] = []
        for step in self._steps(verified, plan):
            try:
                step.do()
                done.append(step)
                if not step.verify():
                    raise UpdateRejectedError(f"the step {step.name} did not verify")
            except Exception as failure:
                self._roll_back(done, plan, reason=f"{step.name}: {failure}")
                raise UpdateRejectedError(
                    f"update to {verified.version} rolled back at {step.name}"
                ) from failure
            self._record("update.step", "succeeded", {"step": step.name, "to": verified.version})
        self._write(INSTALLED, verified.version)
        (self._state / PLAN).unlink()
        self._record("update.applied", "succeeded", {"from": installed, "to": verified.version})
        return verified.version

    def _roll_back(self, done: list[Step], plan: dict[str, Any], reason: str) -> None:
        for step in reversed(done):
            step.undo()
        (self._state / PLAN).unlink(missing_ok=True)
        self._record(
            "update.rolled_back",
            "failed",
            {"to": plan["to"], "back_to": plan["from"], "reason": reason[:200]},
        )

    def recover(self) -> bool:
        """At start: an update the process did not finish is taken back to where it began."""
        plan = self._plan()
        if plan is None:
            return False
        for entry in reversed(plan["done"]):
            self._orchestrator.deploy(entry["service"], entry["previous"])
        (self._state / PLAN).unlink()
        self._record("update.recovered", "succeeded", {"to": plan["to"], "back_to": plan["from"]})
        return True


__all__ = [
    "Orchestrator",
    "Step",
    "UpdateRejectedError",
    "Updater",
    "VerifiedBundle",
    "verify_bundle",
]
