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
