"""ARG-092/099 · the operation screen through the API (F10-07).

`GET /operations/status` answers the eight traffic lights of the operation dashboard, read from
Prometheus, and the alerts Alertmanager has delivered, each with its runbook. `GET
/operations/runbooks/{id}` gives the text of a runbook. Alertmanager delivers on
`POST /internal/alertmanager`, outside the contract, with its own token.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.operations import LIGHTS, MemoryAlerts
from argos_auth import Identity, JwtValidator

REPO = Path(__file__).resolve().parents[3]
RUNBOOKS = REPO / "docs" / "operacion" / "runbooks"
TOKEN = "test-alertmanager-token"  # noqa: S105 - a test value


class Tokens:
    def validate(self, token: str) -> Identity:
        return Identity(sub=token, name=token, roles=frozenset({token}), amr=frozenset({"pwd"}))


class Metrics:
    """Prometheus as a dictionary: the value of each expression, or nothing."""

    def __init__(self, values: Mapping[str, float | None]) -> None:
        self.values = values

    def query(self, expr: str) -> float | None:
        return self.values.get(expr)


HEALTHY = {
    "min(argos_journal_verify_ok)": 1.0,
    "argos_worm_healthy": 1.0,
    'min(up{job=~"argos-.*"})': 1.0,
    "argos_tsa_queue_pending": 3.0,
    "argos_backup_last_restore_test_success": 1.0,
    "argos_evidence_volume_used_ratio": 0.2,
    "argos_certs_expiring_7d": 0.0,
}


def _client(metrics: Metrics | None = None, alerts: MemoryAlerts | None = None) -> TestClient:
    app = create_app(
        cast(JwtValidator, Tokens()),
        operations_metrics=metrics or Metrics(HEALTHY),
        operations_alerts=alerts or MemoryAlerts(),
        runbooks_dir=RUNBOOKS,
        alertmanager_token=TOKEN,
    )
    return TestClient(app)


def _as(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}"}


def _notification(status: str = "firing") -> dict[str, Any]:
    return {
        "version": "4",
        "status": status,
        "alerts": [
            {
                "status": status,
                "fingerprint": "abc123",
                "labels": {"alertname": "WormWriteFailing", "severity": "critical"},
                "annotations": {
                    "summary": "The WORM store does not keep what it is given",
                    "runbook_url": "docs/operacion/runbooks/RB-02-almacen-evidencia.md",
                },
                "startsAt": "2026-09-25T08:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ],
    }


def test_the_eight_lights_come_in_the_order_of_the_dashboard() -> None:
    body = _client().get(f"{API_PREFIX}/operations/status", headers=_as("platform_admin")).json()
    assert [light["key"] for light in body["lights"]] == [light.key for light in LIGHTS]
    assert len(body["lights"]) == 8
    states = {light["key"]: light["state"] for light in body["lights"]}
    assert all(state == "green" for key, state in states.items() if key != "version")


def test_a_broken_journal_and_a_missing_metric_are_red_and_unknown() -> None:
    metrics = Metrics({**HEALTHY, "min(argos_journal_verify_ok)": 0.0, "argos_worm_healthy": None})
    body = _client(metrics).get(f"{API_PREFIX}/operations/status", headers=_as("platform_admin"))
    states = {light["key"]: light["state"] for light in body.json()["lights"]}
    assert states["journal"] == "red"
    # A light nobody measures is not green: the operator must see that it is blind.
    assert states["worm"] == "unknown"


def test_an_alert_delivered_by_alertmanager_appears_with_its_runbook() -> None:
    alerts = MemoryAlerts()
    client = _client(alerts=alerts)
    answer = client.post(
        "/internal/alertmanager", json=_notification(), headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert answer.status_code == 204
    body = client.get(f"{API_PREFIX}/operations/status", headers=_as("read_only_auditor")).json()
    [alert] = body["alerts"]
    assert alert["alertname"] == "WormWriteFailing"
    assert alert["severity"] == "critical"
    assert alert["runbook"] == "RB-02-almacen-evidencia"
    # Resolved, it leaves the list of active alerts.
    client.post(
        "/internal/alertmanager",
        json=_notification("resolved"),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = client.get(f"{API_PREFIX}/operations/status", headers=_as("read_only_auditor")).json()
    assert body["alerts"] == []


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic abc"])
def test_the_webhook_refuses_a_caller_without_the_token(header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    answer = _client().post("/internal/alertmanager", json=_notification(), headers=headers)
    assert answer.status_code == 401


def test_the_webhook_is_closed_when_no_token_is_configured() -> None:
    app = create_app(cast(JwtValidator, Tokens()), operations_alerts=MemoryAlerts())
    answer = TestClient(app).post(
        "/internal/alertmanager", json=_notification(), headers={"Authorization": "Bearer x"}
    )
    assert answer.status_code == 503


def test_a_runbook_is_given_as_markdown_and_nothing_else_is() -> None:
    client = _client()
    body = client.get(
        f"{API_PREFIX}/operations/runbooks/RB-02-almacen-evidencia", headers=_as("platform_admin")
    )
    assert body.status_code == 200
    assert body.json()["markdown"].startswith("# RB-02")
    for wrong in ("RB-99-nope", "..%2F..%2Fpyproject", "RB-02-almacen-evidencia.md"):
        answer = client.get(
            f"{API_PREFIX}/operations/runbooks/{wrong}", headers=_as("platform_admin")
        )
        assert answer.status_code == 404, wrong


@pytest.mark.parametrize("role", ["campaign_manager", "dpo_reviewer"])
def test_only_the_administrator_and_the_auditor_read_the_operation(role: str) -> None:
    answer = _client().get(f"{API_PREFIX}/operations/status", headers=_as(role))
    assert answer.status_code == 403
