"""Chained journal v1: pure hashing, canonicalization and verification (ADR-0002).

Writes live in PostgreSQL (`argos.journal_append`, migration 0001); this module recomputes the
chain with an independent implementation. An intact chain does not prove that trailing entries
were not removed: that is covered by anchoring the head in every sealed campaign (ARG-066).
"""

import hashlib
import json
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError

VERSION = b"ARGOS-JOURNAL-v1"
GENESIS: bytes = hashlib.sha256(b"ARGOS-GENESIS").digest()
_AT_CANON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class JournalVerificationError(IntegrityError):
    """The journal chain is not intact."""


@dataclass(frozen=True, slots=True)
class JournalEntry:
    seq: int
    at_canon: str
    actor: str
    action: str
    payload_canon: str
    prev_hash: bytes
    entry_hash: bytes


@dataclass(frozen=True, slots=True)
class Anomaly:
    seq: int
    reason: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: int
    head_seq: int
    head_hash: bytes
    anomalies: tuple[Anomaly, ...]

    @property
    def intact(self) -> bool:
        return not self.anomalies


def _lp(text: str) -> bytes:
    data = text.encode("utf-8")
    return struct.pack(">I", len(data)) + data


def compute_hash(
    seq: int, at_canon: str, actor: str, action: str, payload_canon: str, prev_hash: bytes
) -> bytes:
    if seq < 1:
        raise ValueError("seq must be >= 1")
    if not _AT_CANON.match(at_canon):
        raise ValueError(f"at_canon is not in canonical format: {at_canon!r}")
    if len(prev_hash) != 32:
        raise ValueError("prev_hash must be 32 bytes long")
    return hashlib.sha256(
        VERSION
        + struct.pack(">Q", seq)
        + _lp(at_canon)
        + _lp(actor)
        + _lp(action)
        + _lp(payload_canon)
        + prev_hash
    ).digest()


def _check_types(value: Any, path: str) -> None:
    if value is None or isinstance(value, bool | int | str):
        return
    if isinstance(value, float):
        raise ValueError(f"floating point number not allowed at {path}")
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_types(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"non-string key at {path}")
            _check_types(item, f"{path}.{key}")
        return
    raise ValueError(f"unsupported type at {path}: {type(value).__name__}")


def canonicalize(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("journal payload must be a JSON object")
    _check_types(payload, "$")
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verify_entries(
    entries: Iterable[JournalEntry], from_seq: int = 1, prev_hash: bytes = GENESIS
) -> VerificationResult:
    anomalies: list[Anomaly] = []
    expected_seq, expected_prev = from_seq, prev_hash
    verified, head_seq, head_hash = 0, from_seq - 1, prev_hash
    for e in entries:
        verified += 1
        if e.seq != expected_seq:
            anomalies.append(Anomaly(e.seq, f"broken sequence: expected {expected_seq}"))
        if e.prev_hash != expected_prev:
            anomalies.append(Anomaly(e.seq, "prev_hash does not link to the previous entry"))
        try:
            recomputed = compute_hash(
                e.seq, e.at_canon, e.actor, e.action, e.payload_canon, e.prev_hash
            )
        except ValueError as exc:
            anomalies.append(Anomaly(e.seq, f"malformed entry: {exc}"))
        else:
            if recomputed != e.entry_hash:
                anomalies.append(Anomaly(e.seq, "entry_hash does not match the content"))
        expected_seq, expected_prev = e.seq + 1, e.entry_hash
        head_seq, head_hash = e.seq, e.entry_hash
    return VerificationResult(verified, head_seq, head_hash, tuple(anomalies))


def require_integrity(result: VerificationResult) -> None:
    if result.intact:
        return
    first = result.anomalies[0]
    raise JournalVerificationError(
        f"journal is not intact: first anomaly at seq={first.seq} ({first.reason})",
        details={"anomalies": [{"seq": a.seq, "reason": a.reason} for a in result.anomalies[:20]]},
    )
