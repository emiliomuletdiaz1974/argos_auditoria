"""The security log: who tried what, apart from the functional journal (F09-08).

Pure part: what reaches the sink and what is folded. A burst of refusals from one origin cannot
fill the database: the first events of each (kind, outcome, origin) in a window are written one by
one and the rest become a single summary with their count, written when the window ends.
"""

import logging

import pytest

from argos_common import security_log
from argos_common.security_log import Recorder, SecurityEvent


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def written() -> list[SecurityEvent]:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _recorder(written: list[SecurityEvent], clock: Clock) -> Recorder:
    return Recorder(written.append, clock=clock, per_window=3, window=60.0)


def _refusal(origin: str = "10.0.0.1") -> dict[str, object]:
    return {
        "kind": "auth.token_rejected",
        "actor": "anonymous",
        "outcome": "refused",
        "detail": {"reason": "ExpiredSignatureError"},
        "source": "argos-api",
        "origin": origin,
    }


def test_the_first_events_of_a_window_are_written_one_by_one(
    written: list[SecurityEvent], clock: Clock
) -> None:
    recorder = _recorder(written, clock)
    for _ in range(3):
        assert recorder.record(**_refusal())  # type: ignore[arg-type]
    assert [e.kind for e in written] == ["auth.token_rejected"] * 3


def test_a_burst_from_one_origin_is_folded_into_one_summary(
    written: list[SecurityEvent], clock: Clock
) -> None:
    recorder = _recorder(written, clock)
    for _ in range(1000):
        recorder.record(**_refusal())  # type: ignore[arg-type]
    assert len(written) == 3, "the burst does not reach the database one by one"
    clock.now += 61
    recorder.record(**_refusal())  # type: ignore[arg-type]
    summaries = [e for e in written if "suppressed" in e.detail]
    assert len(summaries) == 1
    assert summaries[0].detail["suppressed"] == 997
    assert summaries[0].detail["window_seconds"] == 60
    assert summaries[0].kind == "auth.token_rejected"


def test_each_origin_has_its_own_allowance(written: list[SecurityEvent], clock: Clock) -> None:
    recorder = _recorder(written, clock)
    for origin in ("10.0.0.1", "10.0.0.2"):
        for _ in range(5):
            recorder.record(**_refusal(origin))  # type: ignore[arg-type]
    assert len(written) == 6


def test_flush_writes_the_pending_summaries(written: list[SecurityEvent], clock: Clock) -> None:
    recorder = _recorder(written, clock)
    for _ in range(10):
        recorder.record(**_refusal())  # type: ignore[arg-type]
    recorder.flush()
    assert [e.detail.get("suppressed") for e in written][-1] == 7
    recorder.flush()
    assert len(written) == 4, "a summary is written once"


@pytest.mark.parametrize(
    "detail",
    [{"nested": {"a": 1}}, {"list": [1, 2]}, {"long": "x" * 201}, {"float": 1.5}],
)
def test_the_detail_holds_identifiers_and_reasons_not_contents(
    written: list[SecurityEvent], clock: Clock, detail: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="detail"):
        _recorder(written, clock).record(
            "authz.denied", "user:x", "refused", detail, source="argos-api"
        )


def test_without_a_configured_log_an_event_is_not_lost_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    security_log.reset()
    with caplog.at_level(logging.WARNING):
        security_log.record("content.signature_rejected", "system:x", "refused", {"bundle": "b"})
    assert "security event not recorded" in caplog.text
