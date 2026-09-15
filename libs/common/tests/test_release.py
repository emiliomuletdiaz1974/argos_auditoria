"""Canonical release manifest and offline signature verification (ARG-010)."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.errors import IntegrityError
from argos_common.release import build_manifest, serialize, verify_signature

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


def test_includes_the_hash_of_each_sbom(tmp_path: Path) -> None:
    (tmp_path / "argos-api.spdx.json").write_text("{}", encoding="utf-8")
    m = build_manifest("0.1.0", [IMG_A], tmp_path, BUILT_AT)
    assert m["sboms"] == [
        {
            "file": "argos-api.spdx.json",
            "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        }
    ]


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
