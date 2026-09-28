"""QA-22 (QA-013) · `/metrics` does not walk the whole security log on every scrape.

The chain is verified at most once every five minutes and the last answer is served in between:
a log that grows for months must not push the scrape past its timeout, which would make
`argos_security_chain_ok` disappear instead of saying 0.
"""

from types import SimpleNamespace

from argos_api import security_events
from argos_common import security_log


def test_the_chain_is_verified_at_most_once_per_interval(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    now = [1000.0]

    def verify(dsn: str) -> SimpleNamespace:
        calls.append(dsn)
        return SimpleNamespace(intact=True)

    monkeypatch.setattr(security_log, "verify_chain", verify)
    monkeypatch.setattr(security_events, "_monotonic", lambda: now[0])
    security_events.reset_chain_cache()
    assert security_events.chain_intact("dsn") is True
    now[0] += 60
    assert security_events.chain_intact("dsn") is True
    assert calls == ["dsn"], "within five minutes the last answer is served"
    now[0] += security_events.CHAIN_INTERVAL
    security_events.chain_intact("dsn")
    assert calls == ["dsn", "dsn"]
