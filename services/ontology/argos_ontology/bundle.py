"""Signed ontology bundles: deterministic build, Ed25519 signature and verification (ARG-040).

The bundle travels from the editorial team to appliances, including isolated ones, and is exactly
what an attacker would tamper with (a softened severity, a looser selector). The manifest lists
every file with its SHA-256; the canonical manifest is signed with the content key, separate from
the release key; nothing is loaded before the signature and every hash check out (ADR-0006).
"""

import gzip
import hashlib
import io
import json
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from rdflib import Graph

from argos_common.errors import IntegrityError
from argos_common.release import Signer, serialize, verify_signature
from argos_ontology.store import SEMVER, BundleRecord, store_version
from argos_ontology.vocabulary import bind_prefixes

ARTIFACT = "argos-ontology"
CONTENT_KEY = "argos-content"
MANIFEST_NAME = "manifest.json"
INCLUDED = ("ontology/**/*.ttl", "policies/**/*.rego", "challenges/**/*.yaml")
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 20 * 1024 * 1024


class BundleRejectedError(Exception):
    """The bundle cannot be trusted: bad signature, altered, missing or unexpected content."""


@dataclass(frozen=True, slots=True)
class VerifiedBundle:
    manifest: dict[str, Any]
    files: dict[str, bytes]

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    @property
    def in_force_from(self) -> date:
        return date.fromisoformat(str(self.manifest["in_force_from"]))


def bundle_files(library_dir: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for pattern in INCLUDED:
        for path in library_dir.glob(pattern):
            if path.is_file():
                found[path.relative_to(library_dir).as_posix()] = path.read_bytes()
    return dict(sorted(found.items()))


def bundle_manifest(
    files: Mapping[str, bytes], version: str, in_force_from: date
) -> dict[str, Any]:
    if not SEMVER.match(version):
        raise ValueError(f"ontology version must be MAJOR.MINOR.PATCH: {version!r}")
    return {
        "artifact": ARTIFACT,
        "version": version,
        "in_force_from": in_force_from.isoformat(),
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        ],
    }


def _tar_gz(members: Mapping[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return compressed.getvalue()


def build_bundle(
    library_dir: Path, version: str, in_force_from: date
) -> tuple[bytes, dict[str, Any]]:
    """The same library content, version and date always produce the same bytes."""
    files = bundle_files(library_dir)
    if not files:
        raise ValueError(f"no ontology content under {library_dir}")
    manifest = bundle_manifest(files, version, in_force_from)
    members = {MANIFEST_NAME: serialize(manifest), **files}
    return _tar_gz(members), manifest


def sign_bundle(manifest: Mapping[str, Any], signer: Signer) -> bytes:
    return signer.sign(serialize(dict(manifest)))


def _read_members(bundle: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
            infos = tar.getmembers()
            if len(infos) > MAX_MEMBERS:
                raise BundleRejectedError("too many files in bundle")
            for info in infos:
                path = PurePosixPath(info.name)
                if not info.isfile() or path.is_absolute() or ".." in path.parts:
                    raise BundleRejectedError(f"unsafe bundle member: {info.name!r}")
                if info.size > MAX_MEMBER_BYTES:
                    raise BundleRejectedError(f"bundle member too large: {info.name!r}")
                if info.name in members:
                    raise BundleRejectedError(f"repeated bundle member: {info.name!r}")
                extracted = tar.extractfile(info)
                if extracted is None:  # pragma: no cover - regular files always extract
                    raise BundleRejectedError(f"unreadable bundle member: {info.name!r}")
                members[info.name] = extracted.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BundleRejectedError("bundle is not a valid tar.gz archive") from exc
    return members


def verify_bundle(bundle: bytes, signature: bytes, public_key: bytes) -> VerifiedBundle:
    """Check signature, then that the files are exactly the signed ones with the signed hashes."""
    members = _read_members(bundle)
    raw_manifest = members.pop(MANIFEST_NAME, None)
    if raw_manifest is None:
        raise BundleRejectedError("bundle has no manifest")
    try:
        manifest = json.loads(raw_manifest)
    except ValueError as exc:
        raise BundleRejectedError("manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or serialize(manifest) != raw_manifest:
        raise BundleRejectedError("manifest is not in canonical form")
    try:
        verify_signature(raw_manifest, signature, public_key)
    except IntegrityError as exc:
        raise BundleRejectedError("content signature is not valid") from exc
    if manifest.get("artifact") != ARTIFACT or not SEMVER.match(str(manifest.get("version"))):
        raise BundleRejectedError("manifest does not describe an ontology bundle")
    try:
        date.fromisoformat(str(manifest.get("in_force_from")))
    except ValueError as exc:
        raise BundleRejectedError("manifest in_force_from is not a date") from exc
    signed = {str(f["path"]): str(f["sha256"]) for f in manifest.get("files", [])}
    if set(signed) != set(members):
        missing, extra = sorted(set(signed) - set(members)), sorted(set(members) - set(signed))
        raise BundleRejectedError(
            f"bundle files differ from manifest: missing {missing}, extra {extra}"
        )
    for name, data in members.items():
        if hashlib.sha256(data).hexdigest() != signed[name]:
            raise BundleRejectedError(f"altered file in bundle: {name}")
    return VerifiedBundle(manifest, dict(sorted(members.items())))


def bundle_graph(verified: VerifiedBundle) -> Graph:
    graph = bind_prefixes(Graph())
    for name, data in verified.files.items():
        if name.endswith(".ttl"):
            graph.parse(data=data, format="turtle")
    return graph


def load_bundle(dsn: str, bundle: bytes, signature: bytes, public_key: bytes) -> BundleRecord:
    """Verify first; only a verified bundle reaches the versioned store."""
    verified = verify_bundle(bundle, signature, public_key)
    return store_version(
        dsn,
        verified.version,
        verified.in_force_from,
        bundle_graph(verified),
        hashlib.sha256(bundle).hexdigest(),
        verified.manifest,
        signature,
    )
