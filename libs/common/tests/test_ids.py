"""UUID v7 identifiers (RFC 9562)."""

import time
import uuid
from datetime import UTC, datetime

from argos_common.ids import uuid7


def test_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_sortable_by_time() -> None:
    a = uuid7()
    time.sleep(0.002)
    b = uuid7()
    assert a < b and str(a) < str(b)


def test_current_timestamp() -> None:
    ms = uuid7().int >> 80
    assert abs(ms - int(datetime.now(UTC).timestamp() * 1000)) < 1000


def test_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000
