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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import psycopg
from rdflib import Graph

from argos_common.errors import IntegrityError
from argos_common.release import (
    Signer,
    key_fingerprint,
    require_trusted_key,
    serialize,
    verify_signature,
)
from argos_ontology.store import SEMVER, BundleRecord, store_version
from argos_ontology.vocabulary import bind_prefixes

ARTIFACT = "argos-ontology"
CONTENT_KEY = "argos-content"
MANIFEST_NAME = "manifest.json"
INCLUDED = ("ontology/**/*.ttl", "policies/**/*.rego", "challenges/**/*.yaml")
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 20 * 1024 * 1024
# What a whole bundle may inflate to: a signed library is a few megabytes, and a tar.gz from a
# removable medium is untrusted until its manifest checks out (security review F09-02, SEC-019).
MAX_TOTAL_BYTES = 200 * 1024 * 1024


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


def _members(bundle: bytes) -> Iterator[tuple[str, int, Any]]:
    """The members in the order they were written, read as a stream: never all at once."""
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r|gz") as tar:
            for count, info in enumerate(tar, start=1):
                if count > MAX_MEMBERS:
                    raise BundleRejectedError("too many files in bundle")
                path = PurePosixPath(info.name)
                if not info.isfile() or path.is_absolute() or ".." in path.parts:
                    raise BundleRejectedError(f"unsafe bundle member: {info.name!r}")
                if info.size > MAX_MEMBER_BYTES:
                    raise BundleRejectedError(f"bundle member too large: {info.name!r}")
                yield info.name, info.size, tar.extractfile(info)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BundleRejectedError("bundle is not a valid tar.gz archive") from exc


def _checked_manifest(raw_manifest: bytes, signature: bytes, public_key: bytes) -> dict[str, Any]:
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
    return manifest


def verify_bundle(bundle: bytes, signature: bytes, public_key: bytes) -> VerifiedBundle:
    """Signature first, then exactly the signed files with the signed hashes, read as a stream.

    The manifest is the first member: it is verified before any other member is read, a member
    nobody signed is refused before its content is read, and the whole stream has a ceiling.
    """
    stream = _members(bundle)
    first = next(stream, None)
    if first is None or first[0] != MANIFEST_NAME or first[2] is None:
        raise BundleRejectedError("the manifest must be the first member of the bundle")
    manifest = _checked_manifest(first[2].read(), signature, public_key)
    signed = {str(f["path"]): str(f["sha256"]) for f in manifest.get("files", [])}
    files: dict[str, bytes] = {}
    total = 0
    for name, size, handle in stream:
        if name not in signed:
            raise BundleRejectedError(f"bundle member not signed: {name!r}")
        if name in files:
            raise BundleRejectedError(f"repeated bundle member: {name!r}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise BundleRejectedError("bundle too large once inflated")
        data = handle.read() if handle is not None else b""
        if hashlib.sha256(data).hexdigest() != signed[name]:
            raise BundleRejectedError(f"altered file in bundle: {name}")
        files[name] = data
    missing = sorted(set(signed) - set(files))
    if missing:
        raise BundleRejectedError(f"bundle files differ from manifest: missing {missing}")
    return VerifiedBundle(manifest, dict(sorted(files.items())))


def bundle_graph(verified: VerifiedBundle) -> Graph:
    graph = bind_prefixes(Graph())
    for name, data in verified.files.items():
        if name.endswith(".ttl"):
            graph.parse(data=data, format="turtle")
    return graph


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _newest_loaded(dsn: str) -> str | None:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT version FROM argos.ontology_bundles").fetchall()
    versions = [str(row[0]) for row in rows if SEMVER.match(str(row[0]))]
    return max(versions, key=_semver) if versions else None


def load_bundle(
    dsn: str,
    bundle: bytes,
    signature: bytes,
    public_key: bytes,
    *,
    fingerprint: str | None,
    allow_rollback: bool = False,
) -> BundleRecord:
    """Verify first; only a verified bundle from the pinned key reaches the versioned store.

    The key must match the fingerprint pinned by whoever runs this (configuration, operator), and
    a version older than one already loaded is refused unless the rollback is explicit: 1.1.0 after
    1.1.1 would bring back what 1.1.1 corrected (security review F09-02, SEC-020).
    """
    require_trusted_key(public_key, fingerprint)
    verified = verify_bundle(bundle, signature, public_key)
    newest = _newest_loaded(dsn)
    if newest is not None and _semver(verified.version) < _semver(newest) and not allow_rollback:
        raise BundleRejectedError(
            f"bundle {verified.version} is older than {newest}, already loaded: not a rollback"
        )
    return store_version(
        dsn,
        verified.version,
        verified.in_force_from,
        bundle_graph(verified),
        hashlib.sha256(bundle).hexdigest(),
        verified.manifest,
        signature,
    )


def verify_on_disk(dsn: str, version: str, library_dir: Path) -> str:
    """The library a process is about to run is exactly the signed bundle `version`.

    Challenges, policies and shapes are read from disk when a campaign runs; they are trusted only
    when every file matches the manifest that was verified when the bundle was loaded (SEC-011).
    Returns the SHA-256 of that bundle.
    """
    sha256, signed = signed_files(dsn, version)
    on_disk = {
        name: hashlib.sha256(data).hexdigest() for name, data in bundle_files(library_dir).items()
    }
    differ = sorted(n for n in set(signed) | set(on_disk) if signed.get(n) != on_disk.get(n))
    if differ:
        raise IntegrityError(f"the content on disk is not the signed bundle {version}: {differ}")
    return sha256


def signed_files(dsn: str, version: str) -> tuple[str, dict[str, str]]:
    """The SHA-256 of the bundle `version` and the hash of every file its manifest signed."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT sha256, manifest FROM argos.ontology_bundles WHERE version = %s", (version,)
        ).fetchone()
    if row is None:
        raise IntegrityError(f"the ontology {version} was not loaded from a bundle")
    signed = {str(f["path"]): str(f["sha256"]) for f in dict(row[1] or {}).get("files", [])}
    if not signed:
        raise IntegrityError(f"the ontology {version} has no signed manifest to check against")
    return str(row[0]), signed


def verify_running_policies(dsn: str, version: str, loaded: Mapping[str, str]) -> None:
    """The Rego OPA is running is exactly the signed bundle `version`, tests aside (SEC-011)."""
    _, signed = signed_files(dsn, version)
    expected = {
        path: digest
        for path, digest in signed.items()
        if path.startswith("policies/") and path.endswith(".rego") and "_test" not in path
    }
    # The `auth` mount is OPA's own access rule (deploy), not library content; anything else counts.
    running = {
        "policies/" + PurePosixPath(module_id).name: hashlib.sha256(raw.encode("utf-8")).hexdigest()
        for module_id, raw in loaded.items()
        if module_id.endswith(".rego") and PurePosixPath(module_id.lstrip("/")).parts[0] != "auth"
    }
    differ = sorted(n for n in set(expected) | set(running) if expected.get(n) != running.get(n))
    if differ:
        raise IntegrityError(f"OPA is not running the signed bundle {version}: {differ}")


def publish_library(
    dsn: str, library_dir: Path, version: str, in_force_from: date, signer: Signer
) -> BundleRecord:
    """Build, sign and load the library as one bundle, pinning the signer's own key.

    For the development environment, the demonstration and tests: an appliance loads bundles that
    arrive signed, through the airlock, with the fingerprint pinned by its operator.
    """
    bundle, manifest = build_bundle(library_dir, version, in_force_from)
    public_key = signer.public_key()
    return load_bundle(
        dsn,
        bundle,
        sign_bundle(manifest, signer),
        public_key,
        fingerprint=key_fingerprint(public_key),
    )
