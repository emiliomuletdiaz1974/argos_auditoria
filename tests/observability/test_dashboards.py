"""ARG-092 · the dashboards are provisioned from the repository, never built by hand (F10-04).

Three dashboards in platform/observability/dashboards: operation, compliance in figures and the AI
platform. The operation one opens with the row of eight traffic lights of the phase document; every
expression uses a metric that ARGOS publishes, as the alert rules do.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from .test_alert_rules import STANDARD, _published

REPO = Path(__file__).resolve().parents[2]
DASHBOARDS = REPO / "platform" / "observability" / "dashboards"
EXPECTED = {"operation.json": "argos-operation", "compliance.json": "argos-compliance",
            "ai-platform.json": "argos-ai-platform"}  # fmt: skip
LIGHTS = [
    "Diario",
    "Almacén WORM",
    "Servicios",
    "Cola de sellado",
    "Copias",
    "Disco de evidencia",
    "Certificados",
    "Versión",
]


def _load(name: str) -> dict[str, Any]:
    return dict(json.loads((DASHBOARDS / name).read_text(encoding="utf-8")))


def _panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in dashboard["panels"] if p.get("type") != "row"]


def test_the_three_dashboards_exist_with_their_uid() -> None:
    assert {p.name for p in DASHBOARDS.glob("*.json")} == set(EXPECTED)
    for name, uid in EXPECTED.items():
        dashboard = _load(name)
        assert dashboard["uid"] == uid
        assert dashboard["title"]
        assert _panels(dashboard)


def test_the_operation_dashboard_opens_with_the_eight_lights() -> None:
    panels = _panels(_load("operation.json"))
    top = sorted((p for p in panels if p["gridPos"]["y"] == 0), key=lambda p: p["gridPos"]["x"])
    assert [p["title"] for p in top] == LIGHTS
    assert all(p["type"] == "stat" for p in top)
    # Each light turns red or green by its thresholds, not by the eye of the reader.
    for panel in top[:-1]:
        steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
        assert {step["color"] for step in steps} >= {"red", "green"}, panel["title"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_expression_uses_a_published_metric(name: str) -> None:
    published = _published() | STANDARD
    for panel in _panels(_load(name)):
        for target in panel["targets"]:
            used = set(re.findall(r"\b(argos_[a-z0-9_]+|up)\b", target["expr"]))
            assert used, (name, panel["title"])
            assert used <= published, (name, panel["title"], used - published)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_panel_reads_the_provisioned_prometheus(name: str) -> None:
    for panel in _panels(_load(name)):
        assert panel["datasource"] == {"type": "prometheus", "uid": "prometheus"}, panel["title"]
