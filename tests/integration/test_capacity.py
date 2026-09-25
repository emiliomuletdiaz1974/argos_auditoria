"""ARG-098 · where the appliance stands against its size, and the local series (F10-08).

The four dimensions are measured on the database: registered systems, nodes of the latest inventory
snapshot, campaigns pinned or running and AI tokens of the last 24 hours. A snapshot a day keeps
thirteen months of history, which never leaves the appliance.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from argos_common.capacity import limits_of, measure, take_snapshot, usage

pytestmark = pytest.mark.integration

SIZES = Path(__file__).resolve().parents[2] / "platform" / "operation" / "sizes.yaml"


def _systems(dsn: str, n: int) -> None:
    with psycopg.connect(dsn) as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO argos.systems (id, name, kind, connection)"
                " VALUES (%s, %s, 'rdbms', %s)",
                (str(uuid.uuid4()), f"system-{i}", json.dumps({"secret": "connectors/x"})),
            )


def test_the_four_dimensions_are_measured(migrated_db: str) -> None:
    _systems(migrated_db, 3)
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "INSERT INTO argos.ai_usage (service, model, prompt_sha256, tokens_in, tokens_out,"
            " duration_ms) VALUES ('assistant', 'm', repeat('a', 64), 1000, 500, 10)"
        )
        conn.execute(
            "INSERT INTO argos.inventory_snapshots (id, label, taken_at, node_count, content_hash)"
            " VALUES (gen_random_uuid(), 'test', now(), 1234, repeat('b', 64))"
        )
    assert measure(migrated_db) == {
        "systems": 3,
        "assets": 1234,
        "parallel_campaigns": 0,
        "ai_tokens_per_day": 1500,
    }


def test_the_usage_says_the_band_of_each_dimension(migrated_db: str) -> None:
    _systems(migrated_db, 32)  # 80 % of the 40 systems of an S
    rows = {row["dimension"]: row for row in usage(migrated_db, "S", limits_of(SIZES, "S"))}
    assert rows["systems"]["band"] == "amber"
    assert rows["systems"]["used"] == 32 and rows["systems"]["limit"] == 40
    assert rows["assets"]["band"] == "green"


def test_a_snapshot_a_day_and_thirteen_months_of_history(migrated_db: str) -> None:
    limits = limits_of(SIZES, "M")
    old = datetime.now(UTC) - timedelta(days=400)
    take_snapshot(migrated_db, "M", limits, at=old)
    take_snapshot(migrated_db, "M", limits)
    take_snapshot(migrated_db, "M", limits)  # the same day again: one row per day and dimension
    with psycopg.connect(migrated_db) as conn:
        days = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT taken_on FROM argos.capacity_snapshots ORDER BY 1"
            ).fetchall()
        ]
    assert days == [date.today()]


@pytest.mark.parametrize("role", ["svc_api", "svc_health"])
def test_the_services_that_measure_can_measure_with_their_own_role(
    migrated_db: str, role: str
) -> None:
    # A missing grant would refuse every registration, or leave the series empty.
    measured = measure(f"{migrated_db}?options=-c%20role%3D{role}")
    assert set(measured) == {"systems", "assets", "parallel_campaigns", "ai_tokens_per_day"}
