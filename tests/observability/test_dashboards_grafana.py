"""ARG-092 · Grafana loads the three dashboards from the repository (F10-04).

Against the Grafana of the development environment: the provisioned dashboards are there, read-only,
and every query of the operation dashboard answers through the provisioned Prometheus.
"""

import json
import urllib.parse
import urllib.request
from typing import Any

import pytest

pytestmark = pytest.mark.integration

GRAFANA = "http://127.0.0.1:3000"
UIDS = {"argos-operation", "argos-compliance", "argos-ai-platform"}


def _get(path: str) -> Any:
    with urllib.request.urlopen(f"{GRAFANA}{path}", timeout=10) as response:  # noqa: S310
        return json.loads(response.read())


def test_the_three_dashboards_are_provisioned() -> None:
    found = {d["uid"] for d in _get("/api/search?tag=argos")}
    assert found >= UIDS


def test_a_provisioned_dashboard_cannot_be_saved_from_the_interface() -> None:
    meta = _get("/api/dashboards/uid/argos-operation")["meta"]
    assert meta["provisioned"] is True
    assert meta["canSave"] is False


def test_the_lights_answer_through_the_provisioned_prometheus() -> None:
    dashboard = _get("/api/dashboards/uid/argos-operation")["dashboard"]
    lights = [p for p in dashboard["panels"] if p["gridPos"]["y"] == 0]
    for panel in lights:
        query = urllib.parse.quote(panel["targets"][0]["expr"])
        answer = _get(f"/api/datasources/proxy/uid/prometheus/api/v1/query?query={query}")
        assert answer["status"] == "success", panel["title"]
        assert answer["data"]["result"], panel["title"]
