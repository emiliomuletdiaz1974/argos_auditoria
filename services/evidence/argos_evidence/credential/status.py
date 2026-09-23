"""Bitstring Status List (W3C), the revocation list of the credentials (ARG-068).

A list is 131 072 bits (16 KiB), the minimum the specification sets so that a
single index says little about who is being checked. Index 0 is the leftmost
bit of the first byte. The published form is the GZIP of the bitstring in
base64url multibase; GZIP runs with a fixed modification time so the same bits
always give the same text.
"""

from __future__ import annotations

import gzip
import zlib
from collections.abc import Iterable

from argos_evidence.credential.multibase import base64url_multibase, multibase_decode

LIST_SIZE = 131_072


def new_bitstring() -> bytearray:
    return bytearray(LIST_SIZE // 8)


def _check(index: int) -> None:
    if not 0 <= index < LIST_SIZE:
        raise IndexError(f"status index {index} is outside a list of {LIST_SIZE}")


def set_bit(bits: bytearray, index: int) -> None:
    _check(index)
    bits[index // 8] |= 0x80 >> (index % 8)


def is_set(bits: bytes | bytearray, index: int) -> bool:
    _check(index)
    return bool(bits[index // 8] & (0x80 >> (index % 8)))


def bitstring_with(indices: Iterable[int]) -> bytearray:
    bits = new_bitstring()
    for index in indices:
        set_bit(bits, index)
    return bits


def encode_list(bits: bytes | bytearray) -> str:
    return base64url_multibase(gzip.compress(bytes(bits), mtime=0))


MAX_LIST_BYTES = 16 * LIST_SIZE // 8  # up to 16 lists' worth; a list from a bundle is untrusted


def decode_list(encoded: str) -> bytearray:
    """The bits of a published list, decompressed with a ceiling (a gzip bomb stops there)."""
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    bits = bytearray(inflater.decompress(multibase_decode(encoded), MAX_LIST_BYTES + 1))
    if len(bits) > MAX_LIST_BYTES or inflater.unconsumed_tail:
        raise ValueError(f"a status list decompresses to more than {MAX_LIST_BYTES} bytes")
    if len(bits) * 8 < LIST_SIZE:
        raise ValueError("a status list is at least 131072 bits long")
    return bits
