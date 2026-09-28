"""QA-22 · nothing of the health service stays green without a measure behind it.

Findings of the quality review (docs/calidad/revision-qa-f01-f10.md):
- QA-078: a fact carries the time of the check that produced it, not the time it was published;
- QA-079: a check that fails, or cannot measure, says so in `argos_health_check_ok{check}`, which
  has its own alert;
- QA-088: only the certificates of the services the appliance runs count; a retired name does not
  count forever, and an expected service without a certificate does.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

import argos_health.monitor as monitor_module
from argos_health.measures import certificates_expiring
from argos_health.monitor import Monitor

REPO = Path(__file__).resolve().parents[3]
T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> dt.datetime:
        return self.now


def _gauge(monitor: Monitor, name: str, **labels: str) -> float | None:
    for observation in monitor.observations():
        if observation.name == name and all(
            observation.labels.get(k) == v for k, v in labels.items()
        ):
            return observation.value
    return None


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> tuple[Monitor, Clock]:
    monkeypatch.setattr(monitor_module, "journal_ok", lambda dsn, tail: True)
    monkeypatch.setattr(monitor_module, "security_log_ok", lambda dsn: True)
    monkeypatch.setattr(monitor_module, "domain_observations", lambda dsn: ([], 0))
    clock = Clock()
    return Monitor("postgresql://unused", None, None, None, clock=clock), clock


def test_a_fact_carries_the_time_of_its_own_check(
    monitor: tuple[Monitor, Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    health, clock = monitor
    health.check_journal()
    health.check_security_log()
    clock.now = T0 + dt.timedelta(minutes=20)  # the journal check hangs from here on
    health.check_domain()
    published: dict[str, Any] = {}
    monkeypatch.setattr(monitor_module, "publish_facts", lambda dsn, facts: published.update(facts))
    health.publish()
    assert published["journal_intact"] == ("1", T0), "a hung check must look stale, not fresh"
    assert published["queues_stalled"][1] == T0 + dt.timedelta(minutes=20)


def test_a_check_that_fails_says_so_in_its_own_gauge(
    monitor: tuple[Monitor, Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    health, _ = monitor
    health.check_domain()
    assert _gauge(health, "argos_health_check_ok", check="domain") == 1

    def broken(dsn: str) -> Any:
        raise RuntimeError("permission denied for table campaigns")

    monkeypatch.setattr(monitor_module, "domain_observations", broken)
    health.check_domain()
    assert _gauge(health, "argos_health_check_ok", check="domain") == 0


def test_certificates_and_volume_that_cannot_be_measured_are_not_healthy(
    monitor: tuple[Monitor, Clock],
) -> None:
    health, _ = monitor
    health.check_certificates()  # no PKI configured
    health.check_volume()  # no evidence path configured
    assert _gauge(health, "argos_health_check_ok", check="certificates") == 0
    assert _gauge(health, "argos_health_check_ok", check="volume") == 0


def test_only_the_services_the_appliance_runs_count_for_certificates() -> None:
    certificates = [
        {"common_name": "api", "not_after": T0 + dt.timedelta(days=20)},
        {"common_name": "challenge-api", "not_after": T0 - dt.timedelta(days=90)},  # retired
    ]
    assert certificates_expiring(certificates, T0, expected={"api"}) == []
    assert certificates_expiring(certificates, T0, expected={"api", "nats"}) == ["nats"]


def test_there_is_an_alert_for_a_failing_health_check() -> None:
    table = yaml.safe_load((REPO / "platform/observability/objectives.yaml").read_text("utf-8"))
    [row] = [o for o in table["objectives"] if o.get("alert") == "HealthCheckFailing"]
    assert "argos_health_check_ok" in row["expr"]


def test_the_health_service_expects_the_certificates_the_issuer_renews() -> None:
    compose = yaml.safe_load((REPO / "deploy/dev/compose.yaml").read_text(encoding="utf-8"))
    issuer = compose["services"]["cert-issuer"]["environment"]["ARGOS_TLS_SERVICES"]
    health = compose["services"]["health"]["environment"]["ARGOS_HEALTH_TLS_SERVICES"]
    assert health == issuer
