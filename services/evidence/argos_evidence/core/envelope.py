"""The signed envelope of a campaign root, checked with the public key alone (ARG-064).

Part of the pure verification core: no database, no store, no network.
"""

from __future__ import annotations

import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from argos_common.journal import canonicalize


def key_id(public_key: bytes) -> str:
    """Stable name of a key: the first 128 bits of the SHA-256 of its raw public bytes."""
    return hashlib.sha256(public_key).hexdigest()[:32]


def verify_envelope(body: bytes, public_key: bytes) -> bool:
    """True when ``body`` is an envelope signed by ``public_key`` over its payload."""
    try:
        envelope = json.loads(body)
        payload = envelope["payload"]
        signature = bytes.fromhex(envelope["signature"])
        if payload.get("key_id") != key_id(public_key):
            return False
        data = canonicalize(payload).encode("utf-8")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except (ValueError, KeyError, TypeError, AttributeError, InvalidSignature):
        return False
    return True
