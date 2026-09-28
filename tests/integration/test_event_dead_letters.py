"""QA-25 (QA-001) · an event that ran out of deliveries is kept, counted and seen.

Each subscriber writes its dead letters with its own role; the health service reads them with its
own; a resolved one no longer counts.
"""

import psycopg
import pytest

from argos_events import postgres_dead_letter
from argos_health.measures import domain_observations

pytestmark = pytest.mark.integration


def _as(dsn: str, role: str) -> str:
    return f"{dsn}?options=-c%20role%3D{role}"


@pytest.mark.parametrize("role", ["svc_inventory", "svc_challenge", "svc_evidence", "svc_webhook"])
def test_every_subscriber_keeps_its_dead_letters(migrated_db: str, role: str) -> None:
    keep = postgres_dead_letter(_as(migrated_db, role), "svc")
    letter = {"subject": "argos.discovery.table_found", "durable": "inventory-ingest",
              "event": {"id": "e-1", "data": {}}, "error": "RuntimeError: down",
              "deliveries": 5}  # fmt: skip
    keep(letter)
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.event_dead_letters").fetchone() == (1,)


def test_the_health_service_counts_the_open_ones(migrated_db: str) -> None:
    keep = postgres_dead_letter(migrated_db, "inventory-ingest")
    for n in range(3):
        keep({"subject": "argos.discovery.x", "durable": "inventory-ingest",
              "event": {"id": f"e-{n}"}, "error": "x",
              "deliveries": 5})  # fmt: skip
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "UPDATE argos.event_dead_letters SET resolved_at = now() WHERE event_id = 'e-0'"
        )
    observations, _ = domain_observations(_as(migrated_db, "svc_health"))
    [count] = [o.value for o in observations if o.name == "argos_events_dead_letters"]
    assert count == 2
