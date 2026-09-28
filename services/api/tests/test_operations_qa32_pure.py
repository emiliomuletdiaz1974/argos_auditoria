"""Quality review QA-01 · the alert receiver in its edge cases (QA-060, QA-066).

Alertmanager is the only one that calls, but what arrives is still input: a malformed body answers
a reason and never a 500, one bad alert does not cost the rest of the batch, and the order in which
Alertmanager delivers does not leave an alert that is not there.
"""

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from argos_api.app import create_app
from argos_api.operations import MemoryAlerts, _runbook
from argos_auth import Identity, JwtValidator

TOKEN = "test-alertmanager-token"  # noqa: S105 - a test value
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class Tokens:
    def validate(self, token: str) -> Identity:
        return Identity(sub=token, name=token, roles=frozenset({token}), amr=frozenset({"pwd"}))


def _alert(**changes: Any) -> dict[str, Any]:
    alert = {
        "status": "firing",
        "fingerprint": "f1",
        "labels": {"alertname": "WormWriteFailing", "severity": "critical"},
        "annotations": {"summary": "s", "runbook_url": "docs/operacion/runbooks/RB-02-x.md"},
        "startsAt": "2026-09-25T08:00:00Z",
    }
    alert.update(changes)
    return alert


def _client(alerts: MemoryAlerts) -> TestClient:
    app = create_app(
        cast(JwtValidator, Tokens()), operations_alerts=alerts, alertmanager_token=TOKEN
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "body",
    [
        {"alerts": "firing"},
        {"alerts": [_alert(fingerprint=None) | {"fingerprint": None}]},
        {"alerts": [{k: v for k, v in _alert().items() if k != "fingerprint"}]},
        {"alerts": [_alert(startsAt="yesterday")]},
        {"alerts": [_alert(labels="x", annotations=["y"])]},
        {"alerts": ["not an alert"]},
        [],
    ],
)
def test_a_malformed_notification_is_never_a_500(body: Any) -> None:
    answer = _client(MemoryAlerts()).post("/internal/alertmanager", json=body, headers=HEADERS)
    assert answer.status_code in (204, 400), answer.text


def test_one_bad_alert_does_not_cost_the_rest_of_the_batch() -> None:
    alerts = MemoryAlerts()
    body = {"alerts": [{"status": "firing"}, _alert(fingerprint="good")]}
    answer = _client(alerts).post("/internal/alertmanager", json=body, headers=HEADERS)
    assert answer.status_code == 204
    assert [a["alertname"] for a in alerts.active()] == ["WormWriteFailing"]


@pytest.mark.parametrize("name", ["RB-01-x\n", "RB-٠١-x", "RB-01-x\r"])
def test_a_runbook_name_the_database_would_refuse_is_not_a_runbook(name: str) -> None:
    assert _runbook(f"docs/operacion/runbooks/{name}") is None


def test_an_alert_that_fires_again_carries_its_new_start() -> None:
    alerts = MemoryAlerts()
    alerts.receive({"alerts": [_alert()]})
    alerts.receive({"alerts": [_alert(status="resolved")]})
    alerts.receive({"alerts": [_alert(startsAt="2026-09-26T09:00:00Z")]})
    [active] = alerts.active()
    assert active["starts_at"] == "2026-09-26T09:00:00+00:00"


def test_a_late_firing_after_its_resolution_leaves_no_ghost() -> None:
    alerts = MemoryAlerts()
    alerts.receive({"alerts": [_alert(status="resolved")]})
    alerts.receive({"alerts": [_alert()]})  # the same episode, delivered late
    assert alerts.active() == []
