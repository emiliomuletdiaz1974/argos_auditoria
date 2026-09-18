"""Multibase and Multikey encodings used by Data Integrity proofs (ARG-068).

Only what the credential needs: base58btc (prefix ``z``) for signatures and
Multikey public keys, base64url without padding (prefix ``u``) for the status
list. An Ed25519 public Multikey is the multicodec 0xed01 followed by the 32
raw bytes of the key.
"""

from __future__ import annotations

import base64

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}
ED25519_PUBLIC = b"\xed\x01"


def base58btc_encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _ALPHABET[remainder] + encoded
    leading = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading + encoded


def base58btc_decode(text: str) -> bytes:
    number = 0
    for char in text:
        if char not in _INDEX:
            raise ValueError(f"not a base58btc character: {char!r}")
        number = number * 58 + _INDEX[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading = len(text) - len(text.lstrip("1"))
    return b"\x00" * leading + body


def multibase_decode(value: str) -> bytes:
    if value.startswith("z"):
        return base58btc_decode(value[1:])
    if value.startswith("u"):
        payload = value[1:]
        return base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    raise ValueError("only base58btc (z) and base64url (u) multibase values are accepted")


def base64url_multibase(data: bytes) -> str:
    return "u" + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def public_key_multibase(public_key: bytes) -> str:
    if len(public_key) != 32:
        raise ValueError("an Ed25519 public key has 32 bytes")
    return "z" + base58btc_encode(ED25519_PUBLIC + public_key)


def public_key_from_multibase(value: str) -> bytes:
    raw = multibase_decode(value)
    if raw[:2] != ED25519_PUBLIC or len(raw) != 34:
        raise ValueError("not an Ed25519 public Multikey")
    return raw[2:]
