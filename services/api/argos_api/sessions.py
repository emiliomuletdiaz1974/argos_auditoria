"""F09-32 (SEC-060) · sessions closed before their tokens expire.

The API validates access tokens without state; closing a session revokes its refresh token at the
realm, and until now its access token lived on until it expired. The logout records the session
(`sid`) as closed, for longer than any of its access tokens can live, in a table every replica of
the API shares; the guard refuses a token whose session is there.

Each replica keeps its answers for a few seconds so that not every request asks the database: a
closed session is refused at most `cache_seconds` after the logout.
"""

import base64
import binascii
import datetime as dt
import json
import time
from typing import Protocol

import psycopg

# Longer than the access tokens of the realm live (5 minutes), with margin for a longer setting.
CLOSED_FOR = dt.timedelta(minutes=15)
CACHE_SECONDS = 5.0


class SessionClosures(Protocol):
    def close(self, sid: str, until: dt.datetime) -> None: ...
    def is_closed(self, sid: str) -> bool: ...


def sid_of(refresh_token: str) -> str | None:
    """The session a refresh token belongs to, read without verifying it.

    Only used after the realm accepted to revoke that very token: its signature was checked there.
    """
    parts = refresh_token.split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    sid = claims.get("sid") if isinstance(claims, dict) else None
    return str(sid)[:128] if sid else None


class ClosedSessions:
    """The shared store (`argos.closed_sessions`) with a short cache per replica."""

    def __init__(self, dsn: str, cache_seconds: float = CACHE_SECONDS) -> None:
        self._dsn = dsn
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[bool, float]] = {}

    def close(self, sid: str, until: dt.datetime) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO argos.closed_sessions (sid, closed_until) VALUES (%s, %s)"
                " ON CONFLICT (sid) DO UPDATE SET closed_until ="
                " greatest(argos.closed_sessions.closed_until, excluded.closed_until)",
                (sid, until),
            )
            # What no token can use any more is not kept.
            conn.execute("DELETE FROM argos.closed_sessions WHERE closed_until < now()")
        self._cache[sid] = (True, time.monotonic() + self._cache_seconds)

    def _lookup(self, sid: str) -> bool:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT 1 FROM argos.closed_sessions WHERE sid = %s AND closed_until > now()",
                (sid,),
            ).fetchone()
        return row is not None

    def is_closed(self, sid: str) -> bool:
        cached = self._cache.get(sid)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]
        closed = self._lookup(sid)
        self._cache[sid] = (closed, now + self._cache_seconds)
        if len(self._cache) > 10_000:  # a bounded cache: stale entries go first
            self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        return closed
