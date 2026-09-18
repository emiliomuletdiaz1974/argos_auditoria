"""Signed release manifest: the only thing the appliance verifies before trusting a version.

ARG-010 produces it; ARG-086 (updater) verifies it offline with the public key.
"""

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Protocol

import hvac
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .errors import IntegrityError


def build_manifest(
    version: str, images: list[dict[str, str]], sbom_dir: Path | None, built_at: str
) -> dict[str, Any]:
    for image in images:
        if "@sha256:" not in image.get("ref", ""):
            raise ValueError(f"every image must be pinned by digest (name:tag@sha256:…): {image}")
    sboms: list[dict[str, str]] = []
    if sbom_dir is not None and sbom_dir.is_dir():
        for path in sorted(sbom_dir.glob("*.json")):
            sboms.append(
                {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    return {
        "product": "argos",
        "version": version,
        "built": built_at,
        "images": sorted(images, key=lambda i: i["ref"]),
        "sboms": sboms,
    }


def serialize(manifest: dict[str, Any]) -> bytes:
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


class Signer(Protocol):
    def sign(self, data: bytes) -> bytes: ...
    def public_key(self) -> bytes: ...


class VaultTransitSigner:
    """Ed25519 signing with a key that never leaves Vault (transit engine, not exportable)."""

    def __init__(
        self, url: str, token: str, key: str = "argos-release", mount: str = "transit"
    ) -> None:
        self._client = hvac.Client(url=url, token=token)
        self._key_name = key
        self._mount = mount

    def sign(self, data: bytes) -> bytes:
        response = self._client.secrets.transit.sign_data(  # type: ignore[no-untyped-call]
            name=self._key_name,
            hash_input=base64.b64encode(data).decode("ascii"),
            mount_point=self._mount,
        )
        signature: str = response["data"]["signature"]  # "vault:v1:<base64>"
        return base64.b64decode(signature.split(":", 2)[2])

    def public_key(self) -> bytes:
        transit = self._client.secrets.transit
        response = transit.read_key(  # type: ignore[no-untyped-call]
            name=self._key_name, mount_point=self._mount
        )
        versions = response["data"]["keys"]
        latest = versions[str(max(int(v) for v in versions))]
        return base64.b64decode(latest["public_key"])


def key_fingerprint(public_key: bytes) -> str:
    """SHA-256 of the raw public key: what an operator records apart from the artefact."""
    return hashlib.sha256(public_key).hexdigest()


def require_trusted_key(public_key: bytes, fingerprint: str | None) -> None:
    """A key that travels beside the artefact proves nothing: whoever swaps one swaps the other.

    It is trusted only when it matches a fingerprint pinned somewhere else (configuration, image,
    the operator's record).
    """
    if not fingerprint:
        raise IntegrityError("the verifying key is not pinned: pass its fingerprint")
    if not hmac.compare_digest(key_fingerprint(public_key), fingerprint.strip().lower()):
        raise IntegrityError("the verifying key is not the trusted one")


def verify_signature(data: bytes, signature: bytes, public_key: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except (InvalidSignature, ValueError) as exc:
        raise IntegrityError("release manifest signature is not valid") from exc
