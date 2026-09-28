"""Quality review QA-01 · the security log and the JSON logs in their edge cases (QA-002, QA-007).

A short burst ends in silence: its summary must still be written when its window ends, without
waiting for another event of the same key, and the windows that ended must not stay in memory.
A log call that gives context in `extra` must find it in the line.
"""

import io
import json
import logging
from collections.abc import Callable
from typing import Any

from argos_common.logs import configure_logging
from argos_common.security_log import Recorder, SecurityEvent


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Timers:
    """The timers the recorder asks for, fired by the test when it moves the clock."""

    def __init__(self) -> None:
        self.pending: list[tuple[float, Callable[[], None]]] = []

    def __call__(self, delay: float, action: Callable[[], None]) -> None:
        self.pending.append((delay, action))

    def fire(self) -> None:
        pending, self.pending = self.pending, []
        for _, action in pending:
            action()


def test_a_short_burst_ending_in_silence_is_summarised_when_its_window_ends() -> None:
    written: list[SecurityEvent] = []
    clock, timers = Clock(), Timers()
    recorder = Recorder(written.append, clock, per_window=10, window=60.0, timer=timers)
    for _ in range(15):
        recorder.record("auth.login", "user:x", "refused", {}, "api", origin="10.0.0.1")
    assert len(written) == 10
    assert timers.pending, "the first suppressed event must ask for the end of its window"
    clock.now += 61
    timers.fire()
    assert len(written) == 11
    assert written[-1].detail["suppressed"] == 5


def test_the_windows_that_ended_do_not_stay_in_memory() -> None:
    written: list[SecurityEvent] = []
    clock, timers = Clock(), Timers()
    recorder = Recorder(written.append, clock, per_window=1, window=60.0, timer=timers)
    for n in range(100):
        recorder.record("auth.login", f"user:{n}", "refused", {}, "api", origin=f"10.0.0.{n}")
    clock.now += 61
    recorder.record("auth.login", "user:last", "refused", {}, "api", origin="10.9.9.9")
    assert len(recorder._windows) == 1


def test_the_context_given_in_extra_reaches_the_line() -> None:
    stream = io.StringIO()
    configure_logging("svc-test", "INFO", stream)
    logging.getLogger("argos.test.qa33").info(
        "certificate issued", extra={"service": "api", "error": "HTTPError", "kind": "auth"}
    )
    entry: dict[str, Any] = json.loads(stream.getvalue().splitlines()[-1])
    assert entry["error"] == "HTTPError" and entry["kind"] == "auth"
    # The mandatory `service` is the one of the process; the call's goes under its own name.
    assert entry["service"] == "svc-test"
    assert entry["extra_service"] == "api"
