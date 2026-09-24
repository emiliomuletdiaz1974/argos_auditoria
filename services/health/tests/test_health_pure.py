"""ARG-094 · the domain health service, without a database (F10-02).

What no standard exporter measures: the journal and the security log verify, the WORM store keeps
what it is given, the queues flow, the gates are not forgotten, the circuits are closed and the
certificates of the services are not about to expire. Each measure is a function over its source;
these tests give them doubles.
"""

import datetime as dt
from typing import Any

import pytest

from argos_health.measures import (
    Observation,
    as_facts,
    certificates_expiring,
    journal_tail_start,
    render_metrics,
    worm_canary,
)

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)


class _Store:
    """A WORM store double: keeps what it is given, or gives back something else."""

    def __init__(self, corrupt: bool = False, fail: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.retained: dict[str, dt.datetime] = {}
        self._corrupt, self._fail = corrupt, fail

    def put_immutable(self, key: str, data: bytes, retain_until: dt.datetime) -> Any:
        if self._fail:
            raise OSError("store unreachable")
        self.objects[key] = data
        self.retained[key] = retain_until

    def get(self, key: str, version_id: str | None = None) -> bytes:
        data = self.objects[key]
        return data[:-1] + b"?" if self._corrupt else data


def test_the_canary_writes_reads_and_keeps_it_briefly() -> None:
    store = _Store()
    assert worm_canary(store, NOW) is True
    [key] = store.objects
    assert key.startswith("health/canary/")
    # The canary lives in the locked bucket, but only for a day: it is not evidence.
    assert store.retained[key] - NOW == dt.timedelta(days=1)


@pytest.mark.parametrize("store", [_Store(corrupt=True), _Store(fail=True)])
def test_the_canary_fails_when_the_store_does_not_give_back_what_it_kept(store: _Store) -> None:
    assert worm_canary(store, NOW) is False


@pytest.mark.parametrize(
    ("head", "tail", "start"), [(0, 100, 1), (50, 100, 1), (100, 100, 1), (1000, 100, 901)]
)
def test_the_tail_of_the_journal_is_its_last_entries(head: int, tail: int, start: int) -> None:
    assert journal_tail_start(head, tail) == start


def _cert(cn: str, days: float) -> dict[str, Any]:
    return {"common_name": cn, "not_after": NOW + dt.timedelta(days=days)}


def test_a_renewed_certificate_does_not_count_as_expiring() -> None:
    # The issuer renews at 20 days of 30: the old one still exists and expires soon, but the
    # service already uses the new one. What counts is the newest certificate of each name.
    certs = [_cert("api", 3), _cert("api", 29), _cert("nats", 25)]
    assert certificates_expiring(certs, NOW) == []


def test_a_service_whose_newest_certificate_expires_within_seven_days_counts() -> None:
    certs = [_cert("api", 29), _cert("vault", 6.5), _cert("vault", 2)]
    assert certificates_expiring(certs, NOW) == ["vault"]


def test_the_metrics_are_prometheus_text_with_help_type_and_labels() -> None:
    text = render_metrics(
        [
            Observation("argos_journal_verify_ok", 1, help="Whether the journal verifies."),
            Observation(
                "argos_connector_circuit_open",
                1,
                {"system": "dev-source-postgres"},
                help="Circuits open.",
            ),
            Observation(
                "argos_connector_circuit_open", 0, {"system": 'a "quoted" name'}, help="Circuits."
            ),
        ]
    )
    lines = text.splitlines()
    assert "# HELP argos_journal_verify_ok Whether the journal verifies." in lines
    assert "# TYPE argos_journal_verify_ok gauge" in lines
    assert "argos_journal_verify_ok 1" in lines
    assert 'argos_connector_circuit_open{system="dev-source-postgres"} 1' in lines
    assert 'argos_connector_circuit_open{system="a \\"quoted\\" name"} 0' in lines
    # One HELP and one TYPE per metric, not per sample.
    assert sum(line.startswith("# TYPE argos_connector_circuit_open") for line in lines) == 1
    assert text.endswith("\n")


def _journal(scope: str, ok: float) -> Observation:
    return Observation("argos_journal_verify_ok", ok, {"scope": scope})


def test_the_journal_fact_is_intact_only_when_every_verification_passed() -> None:
    passed = [
        _journal("tail", 1),
        _journal("full", 1),
        Observation("argos_security_log_verify_ok", 1),
    ]
    facts = as_facts(passed, 0)
    assert (facts["journal_intact"], facts["security_log_intact"]) == ("1", "1")
    # The full verification failed while the tail still passes: the journal is not intact.
    broken = as_facts([_journal("tail", 1), _journal("full", 0)], 0)
    assert broken["journal_intact"] == "0"
    # Nothing verified yet is not intact either.
    assert as_facts([], 0)["journal_intact"] == "0"
    assert as_facts([], 0)["security_log_intact"] == "0"
