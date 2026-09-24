"""Canonical release manifest and offline signature verification (ARG-010)."""

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.errors import IntegrityError
from argos_common.release import (
    build_manifest,
    key_fingerprint,
    require_trusted_key,
    serialize,
    verify_release_files,
    verify_signature,
)

IMG_A = {"ref": "argos-example:0.1.0@sha256:" + "a" * 64, "component": "ARG-001"}
IMG_B = {"ref": "argos-api:0.1.0@sha256:" + "b" * 64, "component": "ARG-071"}
BUILT_AT = "2026-09-14T10:00:00Z"


def _pub(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_canonical_regardless_of_order() -> None:
    a = serialize(build_manifest("0.1.0", [IMG_A, IMG_B], None, BUILT_AT))
    b = serialize(build_manifest("0.1.0", [IMG_B, IMG_A], None, BUILT_AT))
    assert a == b and a.endswith(b"\n")


def test_requires_images_pinned_by_digest() -> None:
    with pytest.raises(ValueError, match="digest"):
        build_manifest(
            "0.1.0", [{"ref": "argos-api:latest", "component": "ARG-071"}], None, BUILT_AT
        )


def _sboms(folder: Path, *names: str) -> None:
    for name in names:
        (folder / f"{name}.cdx.json").write_text(f'{{"sbom": "{name}"}}', encoding="utf-8")
        (folder / f"{name}.vulns.json").write_text(f'{{"matches": "{name}"}}', encoding="utf-8")


def test_includes_the_hash_of_each_sbom(tmp_path: Path) -> None:
    _sboms(tmp_path, "argos-example")
    (tmp_path / "console.cdx.json").write_text("{}", encoding="utf-8")
    m = build_manifest("0.1.0", [IMG_A], tmp_path, BUILT_AT)
    files = {entry["file"] for entry in m["sboms"]}
    assert files == {"argos-example.cdx.json", "argos-example.vulns.json", "console.cdx.json"}
    console = next(e for e in m["sboms"] if e["file"] == "console.cdx.json")
    assert console["sha256"] == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"


# --- F09-09 (ARG-087): the SBOM and the vulnerability report of each image, under the signature ---


def test_each_image_carries_the_hash_of_its_sbom_and_its_vulnerabilities(tmp_path: Path) -> None:
    _sboms(tmp_path, "argos-example", "argos-api")
    m = build_manifest("0.1.0", [IMG_A, IMG_B], tmp_path, BUILT_AT)
    for image in m["images"]:
        name = image["ref"].split(":")[0]
        sbom = (tmp_path / f"{name}.cdx.json").read_bytes()
        vulns = (tmp_path / f"{name}.vulns.json").read_bytes()
        assert image["sbom_sha256"] == hashlib.sha256(sbom).hexdigest()
        assert image["vulns_sha256"] == hashlib.sha256(vulns).hexdigest()


def test_an_image_without_its_sbom_is_not_released(tmp_path: Path) -> None:
    _sboms(tmp_path, "argos-example")
    with pytest.raises(ValueError, match="argos-api"):
        build_manifest("0.1.0", [IMG_A, IMG_B], tmp_path, BUILT_AT)


def test_the_files_of_the_bundle_are_the_ones_the_manifest_signed(tmp_path: Path) -> None:
    _sboms(tmp_path, "argos-example")
    manifest = build_manifest("0.1.0", [IMG_A], tmp_path, BUILT_AT)
    verify_release_files(manifest, tmp_path)
    (tmp_path / "argos-example.cdx.json").write_text('{"sbom": "changed"}', encoding="utf-8")
    with pytest.raises(IntegrityError, match="argos-example.cdx.json"):
        verify_release_files(manifest, tmp_path)


def test_a_file_the_manifest_lists_must_be_in_the_bundle(tmp_path: Path) -> None:
    _sboms(tmp_path, "argos-example")
    manifest = build_manifest("0.1.0", [IMG_A], tmp_path, BUILT_AT)
    (tmp_path / "argos-example.vulns.json").unlink()
    with pytest.raises(IntegrityError, match="missing"):
        verify_release_files(manifest, tmp_path)


def test_valid_signature() -> None:
    key = Ed25519PrivateKey.generate()
    data = serialize(build_manifest("0.1.0", [IMG_A], None, BUILT_AT))
    verify_signature(data, key.sign(data), _pub(key))


def test_one_altered_byte_invalidates_the_signature() -> None:
    key = Ed25519PrivateKey.generate()
    data = serialize(build_manifest("0.1.0", [IMG_A], None, BUILT_AT))
    signature = key.sign(data)
    altered = data.replace(b"0.1.0", b"0.1.1", 1)
    with pytest.raises(IntegrityError):
        verify_signature(altered, signature, _pub(key))


def test_wrong_key_or_malformed_signature() -> None:
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    data = b"manifest"
    with pytest.raises(IntegrityError):
        verify_signature(data, key.sign(data), _pub(other))
    with pytest.raises(IntegrityError):
        verify_signature(data, b"short", _pub(key))
    with pytest.raises(IntegrityError):
        verify_signature(data, key.sign(data), b"bad-public-key")


def test_a_key_travelling_with_the_artefact_is_trusted_only_by_its_fingerprint() -> None:
    # Whoever replaces the manifest can replace the key beside it: the fingerprint is pinned apart.
    key = _pub(Ed25519PrivateKey.generate())
    require_trusted_key(key, key_fingerprint(key))
    require_trusted_key(key, key_fingerprint(key).upper() + "\n")
    with pytest.raises(IntegrityError, match="not the trusted"):
        require_trusted_key(_pub(Ed25519PrivateKey.generate()), key_fingerprint(key))
    with pytest.raises(IntegrityError, match="not pinned"):
        require_trusted_key(key, None)
