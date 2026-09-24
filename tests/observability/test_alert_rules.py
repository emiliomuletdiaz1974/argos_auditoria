"""ARG-091 · the alert rules come from the specification, not from a template (F10-03).

`platform/observability/objectives.yaml` is the table: each measurable objective of the technical
specification, the metric that watches it, its threshold, its severity and its runbook. The rules
Prometheus loads are generated from it, and these tests keep the table, the rules and the exporters
honest with each other:

- every objective has its alert, or says why it cannot have one yet;
- every alert of every rule file is in the table, and carries its runbook;
- every metric a rule uses is published by some service of ARGOS;
- the generated file is exactly what the generator writes from the table.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
OBJECTIVES = REPO / "platform" / "observability" / "objectives.yaml"
GENERATED = REPO / "platform" / "observability" / "rules" / "argos.rules.yml"
RULE_FILES = [
    GENERATED,
    REPO / "deploy" / "dev" / "prometheus" / "rules" / "security.yml",
    REPO / "deploy" / "dev" / "prometheus" / "rules" / "backup.yml",
]
# Metrics of the exporters that are not ARGOS code (Prometheus itself).
STANDARD = {"up"}
SEVERITIES = {"critical", "warning"}


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("alert_rules", REPO / "tools" / "alert_rules.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _objectives() -> list[dict[str, Any]]:
    return list(yaml.safe_load(OBJECTIVES.read_text(encoding="utf-8"))["objectives"])


def _rules() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in RULE_FILES:
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            found.extend(rule for rule in group["rules"] if "alert" in rule)
    return found


def _published() -> set[str]:
    """Every `argos_*` metric name that appears as a literal in the code of the services."""
    names: set[str] = set()
    for path in (REPO / "services").rglob("*.py"):
        if "tests" in path.parts:
            continue
        names |= set(re.findall(r"\b(argos_[a-z0-9_]+)\b", path.read_text(encoding="utf-8")))
    return names


def test_every_objective_has_an_alert_or_says_why_not() -> None:
    for objective in _objectives():
        assert objective.get("source"), objective["id"]
        if objective.get("pending"):
            assert "alert" not in objective, objective["id"]
            assert len(objective["pending"]) > 20, objective["id"]
            continue
        assert objective["alert"], objective["id"]
        assert objective["severity"] in SEVERITIES, objective["id"]
        assert objective["runbook"].startswith("docs/operacion/runbooks/RB-"), objective["id"]


def test_the_table_and_the_rules_name_the_same_alerts() -> None:
    in_table = {o["alert"] for o in _objectives() if "alert" in o}
    in_rules = {r["alert"] for r in _rules()}
    assert in_table == in_rules


def test_every_alert_carries_its_runbook_severity_and_summary() -> None:
    for rule in _rules():
        assert rule["labels"]["severity"] in SEVERITIES, rule["alert"]
        assert rule["annotations"]["runbook_url"].startswith("docs/operacion/runbooks/RB-")
        assert rule["annotations"]["summary"], rule["alert"]


def test_every_metric_of_a_rule_is_published_by_argos() -> None:
    published = _published() | STANDARD
    for rule in _rules():
        used = set(re.findall(r"\b([a-z_][a-z0-9_]*)\s*(?:\{|\[|\s*[<>=!]|$|\))", rule["expr"]))
        metrics = {m for m in used if m.startswith("argos_") or m in STANDARD}
        assert metrics, rule["alert"]
        missing = metrics - published
        assert not missing, (rule["alert"], missing)


def test_the_generated_rules_are_the_ones_of_the_table() -> None:
    generator = _generator()
    assert GENERATED.read_text(encoding="utf-8") == generator.render(_objectives())


def test_an_objective_without_runbook_is_refused_by_the_generator() -> None:
    generator = _generator()
    broken = [{**_objectives()[0], "runbook": ""}]
    with pytest.raises(ValueError, match="runbook"):
        generator.render(broken)
