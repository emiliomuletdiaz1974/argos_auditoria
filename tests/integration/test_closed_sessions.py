"""F09-32 (SEC-060) · the store of closed sessions, shared by every replica of the API."""

import datetime as dt

import pytest

from argos_api.sessions import ClosedSessions

pytestmark = pytest.mark.integration


def test_a_closed_session_is_seen_by_another_replica_until_it_ends(migrated_db: str) -> None:
    writer, reader = ClosedSessions(migrated_db), ClosedSessions(migrated_db, cache_seconds=0)
    now = dt.datetime.now(dt.UTC)
    assert not reader.is_closed("s-battery")
    writer.close("s-battery", now + dt.timedelta(minutes=15))
    assert reader.is_closed("s-battery"), "another replica sees it"
    writer.close("s-old", now - dt.timedelta(seconds=1))
    assert not reader.is_closed("s-old"), "a closure that ended no longer counts"


def test_closing_twice_keeps_the_later_end(migrated_db: str) -> None:
    store = ClosedSessions(migrated_db, cache_seconds=0)
    now = dt.datetime.now(dt.UTC)
    store.close("s-twice", now + dt.timedelta(minutes=15))
    store.close("s-twice", now + dt.timedelta(minutes=1))
    assert store.is_closed("s-twice")
