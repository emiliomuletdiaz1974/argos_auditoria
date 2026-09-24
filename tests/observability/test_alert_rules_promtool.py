"""ARG-091 · the rules fire when an objective breaks and stay quiet when it holds (F10-03).

`promtool test rules` over tests/observability/argos_rules_test.yml: for every alert of
argos.rules.yml, one case that breaks its objective and one that meets it. The configuration of
Alertmanager is checked with `amtool`. Both run in the pinned images, as in the environment.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
PROMETHEUS = "prom/prometheus:v2.54.1"
ALERTMANAGER = "prom/alertmanager:v0.27.0"
RULES = REPO / "platform" / "observability" / "rules"
CASES = REPO / "tests" / "observability" / "argos_rules_test.yml"
ALERTMANAGER_CONFIG = REPO / "deploy" / "dev" / "alertmanager" / "alertmanager.yml"


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed commands against pinned images
        ["docker", "run", "--rm", *command],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_every_alert_fires_on_its_broken_objective_and_only_then() -> None:
    done = _run(
        "--entrypoint", "promtool",
        "-v", f"{RULES}:/rules:ro", "-v", f"{CASES}:/cases/argos_rules_test.yml:ro",
        PROMETHEUS, "test", "rules", "/cases/argos_rules_test.yml",
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_alert_of_the_file_has_a_firing_and_a_quiet_case() -> None:
    rules = yaml.safe_load((RULES / "argos.rules.yml").read_text(encoding="utf-8"))
    alerts = {r["alert"] for g in rules["groups"] for r in g["rules"]}
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["tests"]
    firing = {t["alertname"] for case in cases for t in case["alert_rule_test"] if t["exp_alerts"]}
    quiet = {
        t["alertname"] for case in cases for t in case["alert_rule_test"] if not t["exp_alerts"]
    }
    assert firing == alerts
    assert quiet == alerts


def test_the_alertmanager_configuration_is_valid() -> None:
    done = _run(
        "--entrypoint", "amtool",
        "-v", f"{ALERTMANAGER_CONFIG}:/etc/alertmanager/alertmanager.yml:ro",
        ALERTMANAGER, "check-config", "/etc/alertmanager/alertmanager.yml",
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr


def test_critical_alerts_repeat_hourly_and_the_rest_daily() -> None:
    config = yaml.safe_load(ALERTMANAGER_CONFIG.read_text(encoding="utf-8"))
    route = config["route"]
    assert route["receiver"] == "console"
    critical = [r for r in route["routes"] if r.get("matchers") == ['severity="critical"']]
    assert critical and critical[0]["repeat_interval"] == "1h"
    assert route["repeat_interval"] == "24h"
