"""Opaque cursors and bounded pages of the inventory API (ARG-029, deviation note ARG-029-030)."""

import base64
import json
from typing import Any

MAX_PAGE_SIZE = 500


def check_first(first: int) -> int:
    if not 1 <= first <= MAX_PAGE_SIZE:
        raise ValueError(f"first must be between 1 and {MAX_PAGE_SIZE}")
    return first


def encode_cursor(value: str | int) -> str:
    raw = json.dumps({"v": value}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode(cursor: str) -> Any:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (ValueError, UnicodeError):  # binascii.Error and JSONDecodeError are ValueErrors
        raise ValueError("invalid cursor") from None
    if not isinstance(data, dict) or set(data) != {"v"}:
        raise ValueError("invalid cursor")
    return data["v"]


def after_key(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    value = _decode(cursor)
    if not isinstance(value, str):
        raise ValueError("invalid cursor")
    return value


def after_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    value = _decode(cursor)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid cursor")
    return value
