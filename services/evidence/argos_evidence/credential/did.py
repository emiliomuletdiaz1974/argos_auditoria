"""The issuer's did:web identity (ARG-068, ADR-0011).

``did:web:<host>`` resolves to ``https://<host>/.well-known/did.json`` (a port
is written ``%3A`` in the DID). The document publishes one Ed25519 Multikey
for assertions: the same key that signs campaign roots (ARG-064).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from argos_evidence.credential.multibase import public_key_multibase

PREFIX = "did:web:"
KEY_FRAGMENT = "key-1"
CONTEXT = ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"]


def did_web(host: str, path: str = "") -> str:
    parts = [quote(host, safe="")] + [p for p in path.strip("/").split("/") if p]
    return PREFIX + ":".join(parts)


def did_web_url(did: str) -> str:
    if not did.startswith(PREFIX):
        raise ValueError(f"not a did:web identifier: {did}")
    host, *path = did[len(PREFIX) :].split(":")
    tail = "/".join(unquote(p) for p in path) + "/did.json" if path else ".well-known/did.json"
    return f"https://{unquote(host)}/{tail}"


def verification_method(did: str) -> str:
    return f"{did}#{KEY_FRAGMENT}"


def did_document(did: str, public_key: bytes) -> dict[str, Any]:
    method = verification_method(did)
    return {
        "@context": list(CONTEXT),
        "id": did,
        "verificationMethod": [
            {
                "id": method,
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": public_key_multibase(public_key),
            }
        ],
        "assertionMethod": [method],
    }
