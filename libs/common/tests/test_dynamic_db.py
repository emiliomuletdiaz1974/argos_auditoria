"""ARG-085 · dynamic database credentials renewed in place (F09-05).

A fake credential source and a fake clock: no Vault and no database. What is checked is the rule
of the renewal, not Vault: a credential is asked for at start, renewed before it expires, written
where libpq reads it for every new connection, and a failed renewal does not bring the service
down while the current credential is still valid.
"""

import logging
from pathlib import Path

import pytest

from argos_common.dynamic_db import (
    DynamicCredentials,
    Lease,
    parse_service_file,
    renewal_delay,
)

HOUR = 3600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Source:
    """Issues leases v-1, v-2, ... and fails on demand."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.issued = 0
        self.failing = False

    def issue(self) -> Lease:
        if self.failing:
            raise ConnectionError("vault is not answering")
        self.issued += 1
        return Lease(f"v-{self.issued}", f"secret-{self.issued}", self.ttl)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _credentials(tmp_path: Path, source: Source, clock: Clock) -> DynamicCredentials:
    return DynamicCredentials(source, tmp_path / "db" / "pg_service.conf", clock=clock)


def test_a_long_credential_is_renewed_an_hour_before_it_expires() -> None:
    assert renewal_delay(24 * HOUR) == 23 * HOUR


def test_a_short_credential_is_renewed_at_half_its_life() -> None:
    assert renewal_delay(60) == 30
    assert renewal_delay(2 * HOUR) == HOUR


def test_the_first_credential_is_written_at_start(tmp_path: Path, clock: Clock) -> None:
    credentials = _credentials(tmp_path, Source(24 * HOUR), clock)
    credentials.start_blocking()
    written = parse_service_file(credentials.service_file)
    assert written == {"argos": {"user": "v-1", "password": "secret-1"}}


def test_a_renewal_replaces_the_credential_in_place(tmp_path: Path, clock: Clock) -> None:
    source = Source(60)
    credentials = _credentials(tmp_path, source, clock)
    credentials.start_blocking()
    clock.now += 30
    wait = credentials.step()
    assert wait == 30
    assert parse_service_file(credentials.service_file)["argos"]["user"] == "v-2"
    leftovers = [p.name for p in credentials.service_file.parent.iterdir()]
    assert leftovers == ["pg_service.conf"], "the file is replaced whole, never half written"


def test_a_failed_renewal_keeps_the_current_credential_and_tries_again(
    tmp_path: Path, clock: Clock
) -> None:
    source = Source(60)
    credentials = _credentials(tmp_path, source, clock)
    credentials.start_blocking()
    clock.now += 30
    source.failing = True
    wait = credentials.step()  # no exception: the service keeps serving
    assert 0 < wait < 30, "it tries again before the current credential runs out"
    assert parse_service_file(credentials.service_file)["argos"]["user"] == "v-1"
    source.failing = False
    clock.now += wait
    credentials.step()
    assert parse_service_file(credentials.service_file)["argos"]["user"] == "v-2"


def test_after_expiry_it_keeps_trying_without_stopping(tmp_path: Path, clock: Clock) -> None:
    source = Source(60)
    credentials = _credentials(tmp_path, source, clock)
    credentials.start_blocking()
    source.failing = True
    clock.now += 120
    assert credentials.step() > 0


def test_a_service_that_cannot_get_its_first_credential_does_not_start(
    tmp_path: Path, clock: Clock
) -> None:
    source = Source(60)
    source.failing = True
    with pytest.raises(ConnectionError):
        _credentials(tmp_path, source, clock).start_blocking()


def test_no_log_line_carries_the_user_or_the_password(
    tmp_path: Path, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    source = Source(60)
    credentials = _credentials(tmp_path, source, clock)
    with caplog.at_level(logging.DEBUG):
        credentials.start_blocking()
        clock.now += 30
        source.failing = True
        credentials.step()
        source.failing = False
        credentials.step()
    text = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    for secret in ("secret-1", "secret-2", "v-1", "v-2"):
        assert secret not in text


@pytest.mark.parametrize("value", ["with\nnewline", "with\rreturn", ""])
def test_a_lease_that_would_break_the_file_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="lease"):
        Lease(value, "password", 60)
    with pytest.raises(ValueError, match="lease"):
        Lease("user", value, 60)
