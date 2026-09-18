"""ARG-040 · deterministic bundles, and nothing is trusted before signature and hashes check."""

import gzip
import importlib.util
import io
import tarfile
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.release import key_fingerprint, serialize
from argos_ontology.bundle import (
    MANIFEST_NAME,
    BundleRejectedError,
    build_bundle,
    bundle_graph,
    sign_bundle,
    verify_bundle,
)
from argos_ontology.vocabulary import ARGOS, CORE_FILE

IN_FORCE = date(2026, 10, 1)


class LocalSigner:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.generate()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / "ontology" / "core").mkdir(parents=True)
    (root / "ontology" / "core" / "argos-core.ttl").write_bytes(CORE_FILE.read_bytes())
    (root / "policies").mkdir()
    (root / "policies" / "retention.rego").write_text("package argos.retention\n", encoding="utf-8")
    (root / "challenges").mkdir()
    (root / "challenges" / "catalog.yaml").write_text("challenges: []\n", encoding="utf-8")
    (root / "ontology" / "editorial").mkdir()
    (root / "ontology" / "editorial" / "OBL-X-1.yaml").write_text("id: x\n", encoding="utf-8")
    return root


def _repack(bundle: bytes, change: dict[str, bytes | None]) -> bytes:
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
        for info in tar.getmembers():
            extracted = tar.extractfile(info)
            assert extracted is not None
            members[info.name] = extracted.read()
    for name, data in change.items():
        if data is None:
            members.pop(name, None)
        else:
            members[name] = data
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


def test_the_same_library_builds_the_same_bytes(library: Path) -> None:
    first, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    (library / "ontology" / "core" / "argos-core.ttl").touch()
    second, _ = build_bundle(library, "1.0.0", IN_FORCE)
    assert first == second
    assert [f["path"] for f in manifest["files"]] == [
        "challenges/catalog.yaml",
        "ontology/core/argos-core.ttl",
        "policies/retention.rego",
    ]


def test_a_signed_bundle_verifies_and_yields_its_graph(library: Path) -> None:
    signer = LocalSigner()
    bundle, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    verified = verify_bundle(bundle, sign_bundle(manifest, signer), signer.public_key())
    assert (verified.version, verified.in_force_from) == ("1.0.0", IN_FORCE)
    assert (ARGOS.Obligation, None, None) in bundle_graph(verified)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"ontology/core/argos-core.ttl": b"# softened\n"}, "altered file"),
        ({"policies/extra.rego": b"package argos.extra\n"}, "extra \\['policies/extra.rego'\\]"),
        ({"challenges/catalog.yaml": None}, "missing \\['challenges/catalog.yaml'\\]"),
        ({MANIFEST_NAME: None}, "no manifest"),
        ({"../evil.ttl": b"x"}, "unsafe bundle member"),
    ],
)
def test_tampered_bundles_are_rejected(
    library: Path, change: dict[str, bytes | None], message: str
) -> None:
    signer = LocalSigner()
    bundle, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    signature = sign_bundle(manifest, signer)
    with pytest.raises(BundleRejectedError, match=message):
        verify_bundle(_repack(bundle, change), signature, signer.public_key())


def test_a_manifest_rewritten_with_matching_hashes_breaks_the_signature(library: Path) -> None:
    signer = LocalSigner()
    bundle, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    signature = sign_bundle(manifest, signer)
    moved = serialize({**manifest, "in_force_from": "2020-01-01"})
    with pytest.raises(BundleRejectedError, match="signature"):
        verify_bundle(_repack(bundle, {MANIFEST_NAME: moved}), signature, signer.public_key())


def test_another_key_is_refused(library: Path) -> None:
    bundle, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    signature = sign_bundle(manifest, LocalSigner())
    with pytest.raises(BundleRejectedError, match="signature"):
        verify_bundle(bundle, signature, LocalSigner().public_key())


def test_garbage_is_not_a_bundle() -> None:
    with pytest.raises(BundleRejectedError, match="valid tar.gz"):
        verify_bundle(b"not a bundle", b"sig", LocalSigner().public_key())


@pytest.mark.parametrize("version", ["1.0", "v1.0.0"])
def test_bundle_versions_are_semver(library: Path, version: str) -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        build_bundle(library, version, IN_FORCE)


def test_an_empty_library_is_not_published(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no ontology content"):
        build_bundle(tmp_path, "1.0.0", IN_FORCE)


def test_the_publish_tool_verifies_and_rejects(library: Path, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "ontology_publish", root / "tools" / "ontology_publish.py"
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    signer = LocalSigner()
    bundle, manifest = build_bundle(library, "1.0.0", IN_FORCE)
    target = tmp_path / "argos-ontology-1.0.0.tar.gz"
    target.write_bytes(bundle)
    tool.signature_path(target).write_bytes(sign_bundle(manifest, signer))
    (tmp_path / "content.pub").write_bytes(signer.public_key())
    pinned = ["--fingerprint", key_fingerprint(signer.public_key())]
    assert tool.main(["verify", str(target), *pinned]) == 0
    # The key beside the bundle alone is not trusted: whoever swaps one swaps the other.
    assert tool.main(["verify", str(target)]) == 1
    target.write_bytes(_repack(bundle, {"policies/retention.rego": b"package argos.softened\n"}))
    assert tool.main(["verify", str(target), *pinned]) == 1
