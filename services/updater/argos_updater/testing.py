"""Update bundles built in memory, for the tests of the updater and of the API (F09-10).

A bundle made here has the shape of `tools/release.py bundle`: a signed manifest, the SBOMs and
reports, and one `docker save` archive per image. The images are synthetic: a configuration and
nothing to run, enough to check that what is verified is what was signed.
"""

import hashlib
import io
import json
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.release import build_manifest, serialize


def public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def image_archive(path: Path, name: str, version: str) -> str:
    """A classic `docker save` archive with one image; returns its id."""
    config = json.dumps({"config": {"Labels": {"org.argos.version": version}}, "name": name})
    data = config.encode()
    digest = hashlib.sha256(data).hexdigest()
    manifest = json.dumps([{"Config": f"blobs/sha256/{digest}", "RepoTags": [f"{name}:{version}"]}])
    with tarfile.open(path, "w") as tar:
        for member, content in (
            ("manifest.json", manifest.encode()),
            (f"blobs/sha256/{digest}", data),
        ):
            info = tarfile.TarInfo(member)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return f"sha256:{digest}"


def signed_bundle(root: Path, version: str, key: Ed25519PrivateKey, images: list[str]) -> Path:
    bundle = root / f"bundle-{version}"
    (bundle / "images").mkdir(parents=True)
    (bundle / "sbom").mkdir()
    listed = []
    for name in images:
        digest = image_archive(bundle / "images" / f"{name}.tar", name, version)
        listed.append({"ref": f"{name}:{version}@{digest}", "component": "ARG-000"})
        (bundle / "sbom" / f"{name}.cdx.json").write_text("{}", encoding="utf-8")
        (bundle / "sbom" / f"{name}.vulns.json").write_text('{"matches": []}', encoding="utf-8")
    manifest = serialize(build_manifest(version, listed, bundle / "sbom", "2026-09-24T00:00:00Z"))
    (bundle / "release-manifest.json").write_bytes(manifest)
    (bundle / "release-manifest.sig").write_bytes(key.sign(manifest))
    return bundle
