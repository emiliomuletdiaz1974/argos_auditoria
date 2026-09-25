"""ARG-092/099 · an alert travels from Alertmanager to the operation screen (F10-07).

Against the development environment: an alert posted to Alertmanager is delivered to the API with
the token of its configuration, and the API keeps it with its runbook for the operation screen.
"""

import json
import time
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from integration.conftest import ADMIN_DSN

pytestmark = pytest.mark.integration

ALERTMANAGER = "http://127.0.0.1:9093/api/v2/alerts"


def test_an_alert_of_alertmanager_reaches_the_api_with_its_runbook() -> None:
    marker = f"delivery-test-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    alert = [
        {
            # A name of its own: an alert of an existing group waits for its group_interval (5 min).
            "labels": {
                "alertname": f"DeliveryTest{marker[-8:]}",
                "severity": "critical",
                "test": marker,
            },  # fmt: skip
            "annotations": {
                "summary": "delivery test of F10-07",
                "runbook_url": "docs/operacion/runbooks/RB-06-plataforma.md",
            },
            "startsAt": now.isoformat(),
            "endsAt": (now + timedelta(minutes=5)).isoformat(),
        }
    ]
    request = urllib.request.Request(  # noqa: S310 - development Alertmanager
        ALERTMANAGER,
        data=json.dumps(alert).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        assert response.status == 200
    row = None
    deadline = time.monotonic() + 90  # critical: group_wait of 10 s, then the delivery
    while row is None and time.monotonic() < deadline:
        with psycopg.connect(ADMIN_DSN) as conn:
            row = conn.execute(
                "SELECT status, runbook FROM argos.operation_alerts WHERE labels->>'test' = %s",
                (marker,),
            ).fetchone()
        time.sleep(2)
    assert row == ("firing", "RB-06-plataforma")
