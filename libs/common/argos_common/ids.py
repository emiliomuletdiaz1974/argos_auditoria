"""UUID v7 identifiers (RFC 9562): sortable by time. Python 3.12 does not provide them."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits
    value = (
        (unix_ms & ((1 << 48) - 1)) << 80  # unix_ts_ms: 48 bits
        | 0x7 << 76  # version 7
        | ((rand >> 62) & 0xFFF) << 64  # rand_a: 12 bits
        | 0b10 << 62  # RFC variant
        | (rand & ((1 << 62) - 1))  # rand_b: 62 bits
    )
    return uuid.UUID(int=value)
