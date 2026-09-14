"""Chained journal v1: the integrity suite is written before the journal (ADR-0002)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from argos_common.journal import (
    GENESIS,
    JournalEntry,
    JournalVerificationError,
    canonicalize,
    compute_hash,
    require_integrity,
    verify_entries,
)

VECTORS_PATH = Path(__file__).parents[3] / "tests" / "vectors" / "journal_v1.json"
VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
T0 = "2026-09-14T10:00:00.000000Z"


def _entries() -> list[JournalEntry]:
    return [
        JournalEntry(
            v["seq"],
            v["at_canon"],
            v["actor"],
            v["action"],
            v["payload_canon"],
            bytes.fromhex(v["prev_hash"]),
            bytes.fromhex(v["entry_hash"]),
        )
        for v in VECTORS["entries"]
    ]


def test_genesis() -> None:
    assert GENESIS.hex() == VECTORS["genesis"]


@pytest.mark.parametrize("v", VECTORS["entries"], ids=lambda v: f"seq{v['seq']}")
def test_reproduces_the_vectors(v: dict[str, Any]) -> None:
    result = compute_hash(
        v["seq"],
        v["at_canon"],
        v["actor"],
        v["action"],
        v["payload_canon"],
        bytes.fromhex(v["prev_hash"]),
    )
    assert result.hex() == v["entry_hash"]


def test_canonicalize_reproduces_the_vectors() -> None:
    e = VECTORS["entries"]
    assert canonicalize({"version": 1, "checksum": "abc"}) == e[0]["payload_canon"]
    # The payload is fixed test data: changing it would change the vector hashes.
    second = canonicalize({"nota": "Aprobación con ñ y €", "campaign_id": "c-1"})
    assert second == e[1]["payload_canon"]


def test_canonicalize_rejects_floats_reporting_the_path() -> None:
    with pytest.raises(ValueError, match=r"\$\.a\[1\]"):
        canonicalize({"a": [1, 2.5]})


def test_canonicalize_rejects_non_json_types() -> None:
    with pytest.raises(ValueError, match="bytes"):
        canonicalize({"a": b"x"})


def test_length_prefix_prevents_ambiguity() -> None:
    assert compute_hash(1, T0, "ab", "c", "{}", GENESIS) != compute_hash(
        1, T0, "a", "bc", "{}", GENESIS
    )


def test_rejects_malformed_input() -> None:
    with pytest.raises(ValueError):
        compute_hash(0, T0, "a", "b", "{}", GENESIS)
    with pytest.raises(ValueError):
        compute_hash(1, "2026-09-14 10:00:00", "a", "b", "{}", GENESIS)
    with pytest.raises(ValueError):
        compute_hash(1, T0, "a", "b", "{}", b"short")


def test_intact_chain() -> None:
    r = verify_entries(_entries())
    assert r.intact
    assert (r.verified, r.head_seq) == (3, 3)
    assert r.head_hash.hex() == VECTORS["entries"][2]["entry_hash"]


def test_tampered_content_reports_the_position() -> None:
    e = _entries()
    e[1] = replace(e[1], payload_canon='{"campaign_id":"c-2","nota":"x"}')
    r = verify_entries(e)
    assert not r.intact
    assert [a.seq for a in r.anomalies] == [2]


def test_removed_entry() -> None:
    e = _entries()
    r = verify_entries([e[0], e[2]])
    assert not r.intact
    assert {a.seq for a in r.anomalies} == {3}


def test_inserted_entry_breaks_the_link() -> None:
    e = _entries()
    intruder = replace(e[1], actor="user:intruder")
    r = verify_entries([e[0], e[1], intruder, e[2]])
    assert not r.intact


def test_range_verification() -> None:
    e = _entries()
    r = verify_entries(e[1:], from_seq=2, prev_hash=e[0].entry_hash)
    assert r.intact and r.verified == 2


def test_invalid_timestamp_is_an_anomaly_not_an_exception() -> None:
    e = _entries()
    e[0] = replace(e[0], at_canon="2026-09-14 10:00:00")
    r = verify_entries(e)
    assert r.anomalies[0].seq == 1


def test_empty_chain_is_intact() -> None:
    r = verify_entries([])
    assert r.intact and r.verified == 0 and r.head_hash == GENESIS


def test_require_integrity_raises_with_details() -> None:
    e = _entries()
    e[2] = replace(e[2], actor="system:other")
    with pytest.raises(JournalVerificationError) as exc:
        require_integrity(verify_entries(e))
    assert exc.value.details["anomalies"][0]["seq"] == 3
