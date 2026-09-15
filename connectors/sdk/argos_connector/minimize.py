"""Keyed pseudonymisation of sampled values (ARG-011): linkable inside a system, never reversible
by hashing a dictionary of candidate values without the per-system key."""

import hashlib
import hmac
from typing import Self

_NULL_MARKER = b"\x00argos:null"


class ValueHasher:
    DIGEST_HEX = 32

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("hash key must be at least 32 bytes")
        self._key = key

    @classmethod
    def from_hex(cls, hex_key: str) -> Self:
        return cls(bytes.fromhex(hex_key))

    def digest(self, value: object) -> str:
        if value is None:
            data = _NULL_MARKER
        elif isinstance(value, bytes):
            data = value
        else:
            data = str(value).encode("utf-8")
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()[: self.DIGEST_HEX]
