"""ARG-092/099 · the alerts of Alertmanager, kept for the operation screen (F10-07)."""

import pytest

from argos_api.operations import PostgresAlerts

pytestmark = pytest.mark.integration


def _notification(status: str, fingerprint: str = "f1") -> dict[str, object]:
    return {
        "alerts": [
            {
                "status": status,
                "fingerprint": fingerprint,
                "labels": {"alertname": "JournalNotIntact", "severity": "critical"},
                "annotations": {
                    "summary": "The chained journal does not verify",
                    "runbook_url": "docs/operacion/runbooks/RB-01-diario.md",
                },
                "startsAt": "2026-09-25T08:00:00Z",
            }
        ]
    }


def test_a_firing_alert_is_active_until_it_is_resolved(migrated_db: str) -> None:
    alerts = PostgresAlerts(migrated_db)
    assert alerts.receive(_notification("firing")) == 1
    [active] = alerts.active()
    assert (active["alertname"], active["runbook"]) == ("JournalNotIntact", "RB-01-diario")
    # Alertmanager repeats the same alert: one row, not two.
    alerts.receive(_notification("firing"))
    assert len(alerts.active()) == 1
    alerts.receive(_notification("resolved"))
    assert alerts.active() == []


def test_a_runbook_the_database_refuses_does_not_lose_the_batch(migrated_db: str) -> None:
    """QA-060: a runbook name with a final newline passed the regular expression and broke the
    CHECK of the table, and every alert of the notification was lost."""
    alerts = PostgresAlerts(migrated_db)
    bad = _notification("firing", "f-bad")["alerts"][0]  # type: ignore[index]
    bad = {**bad, "annotations": {"summary": "x", "runbook_url": "runbooks/RB-01-diario\n"}}
    good = _notification("firing", "f-good")["alerts"][0]  # type: ignore[index]
    alerts.receive({"alerts": [bad, good]})
    assert len(alerts.active()) == 2


def test_the_start_is_renewed_and_a_late_firing_leaves_no_ghost(migrated_db: str) -> None:
    """QA-066."""
    alerts = PostgresAlerts(migrated_db)
    alerts.receive(_notification("firing"))
    alerts.receive(_notification("resolved"))
    alerts.receive(_notification("firing"))  # late: the same episode
    assert alerts.active() == []
    again = _notification("firing")
    again["alerts"][0]["startsAt"] = "2026-09-26T09:00:00Z"  # type: ignore[index]
    alerts.receive(again)
    [active] = alerts.active()
    assert active["starts_at"] == "2026-09-26T09:00:00+00:00"
