"""ARG-023 · pure pieces of the inventory versioning: growth rule, timestamps, snapshot hash."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from argos_inventory.versioning.deltas import GROWTH_FACTOR, is_anomalous_growth, iso_utc
from argos_inventory.versioning.snapshots import snapshot_hash


@pytest.mark.parametrize(
    ("before", "now", "expected"),
    [
        (20000, 70000, True),
        (20000, 60000, False),  # exactly x3 is not above the factor
        (1000, 9000, False),  # needs more than 1000 previous rows
        (1001, 9000, True),
        (None, 70000, False),
        (-1, 70000, False),
    ],
)
def test_growth_rule(before: int | None, now: int, expected: bool) -> None:
    assert GROWTH_FACTOR == 3.0
    assert is_anomalous_growth(before, now) is expected


def test_iso_utc_matches_the_scanner_format() -> None:
    madrid = timezone(timedelta(hours=2))
    moment = datetime(2026, 9, 15, 12, 0, 0, 123456, tzinfo=madrid)
    assert iso_utc(moment) == "2026-09-15T10:00:00.123456+00:00"
    assert iso_utc(moment) == moment.astimezone(UTC).isoformat()


def test_snapshot_hash_is_order_independent_and_content_sensitive() -> None:
    dni = {
        "category": "official_identifier",
        "method": "validator:dni",
        "confidence": "1.0000",
    }
    rows: list[dict[str, Any]] = [
        {
            "node_key": "b",
            "label": "Table",
            "name": "patients",
            "qualified_name": "clinic.patients",
            "system_id": "s1",
            "categories": [],
        },
        {
            "node_key": "a",
            "label": "Column",
            "name": "dni_number",
            "qualified_name": "clinic.x.dni_number",
            "system_id": "s1",
            "categories": [dni],
        },
    ]
    assert snapshot_hash(rows) == snapshot_hash(list(reversed(rows)))
    changed = [dict(rows[0], name="patients2"), rows[1]]
    assert snapshot_hash(changed) != snapshot_hash(rows)
    assert len(snapshot_hash(rows)) == 64
