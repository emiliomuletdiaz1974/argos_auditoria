"""ARG-071 · the cursor and the fingerprint of a request, with no database in the way."""

import pytest

from argos_api.core import request_fingerprint
from argos_api.paging import CursorError, apply_keyset, cursor_for, paginate, position_of

ROWS = [
    {"id": "e", "created_at": "2026-09-20T10:05:00Z"},
    {"id": "d", "created_at": "2026-09-20T10:04:00Z"},
    {"id": "c", "created_at": "2026-09-20T10:03:00Z"},
    {"id": "b", "created_at": "2026-09-20T10:02:00Z"},
    {"id": "a", "created_at": "2026-09-20T10:01:00Z"},
]


def test_the_cursor_says_nothing_about_the_row_it_points_at() -> None:
    cursor = cursor_for("2026-09-20T10:03:00Z", "c")
    assert "2026" not in cursor
    assert "c" not in cursor or len(cursor) > 8  # it is base64, not the value in plain sight
    assert position_of(cursor) == ("2026-09-20T10:03:00Z", "c")


def test_a_cursor_that_is_not_ours_is_refused() -> None:
    for broken in ("not-a-cursor", "", "!!!", cursor_for("x", "y")[:-4]):
        with pytest.raises(CursorError):
            position_of(broken)


def test_no_cursor_means_the_first_page() -> None:
    assert position_of(None) is None


def test_a_page_hands_back_the_cursor_of_its_last_row() -> None:
    page = paginate(ROWS, limit=2)
    assert [row["id"] for row in page.items] == ["e", "d"]
    assert page.next is not None
    assert position_of(page.next) == ("2026-09-20T10:04:00Z", "d")

    last = paginate(apply_keyset(ROWS, position_of(page.next)), limit=10)
    assert [row["id"] for row in last.items] == ["c", "b", "a"]
    assert last.next is None


def test_the_cursor_holds_its_place_when_rows_are_inserted_in_between() -> None:
    first = paginate(ROWS, limit=2)
    newer = [
        {"id": "g", "created_at": "2026-09-20T10:07:00Z"},
        {"id": "f", "created_at": "2026-09-20T10:06:00Z"},
    ]
    grown = newer + ROWS

    second = paginate(apply_keyset(grown, position_of(first.next)), limit=2)
    assert [row["id"] for row in second.items] == ["c", "b"]

    seen = [row["id"] for row in first.items] + [row["id"] for row in second.items]
    assert len(seen) == len(set(seen)), "an offset would have shown 'd' twice"


def test_two_rows_of_the_same_instant_are_still_ordered_by_id() -> None:
    same = [
        {"id": "b", "created_at": "2026-09-20T10:00:00Z"},
        {"id": "a", "created_at": "2026-09-20T10:00:00Z"},
    ]
    page = paginate(same, limit=1)
    assert [row["id"] for row in apply_keyset(same, position_of(page.next))] == ["a"]


def test_the_fingerprint_separates_the_method_the_route_and_the_body() -> None:
    one = request_fingerprint("POST", "/api/v1/campaigns", b'{"name":"A"}')
    assert one == request_fingerprint("POST", "/api/v1/campaigns", b'{"name":"A"}')
    assert one != request_fingerprint("POST", "/api/v1/campaigns", b'{"name":"B"}')
    assert one != request_fingerprint("POST", "/api/v1/credentials", b'{"name":"A"}')
    assert one != request_fingerprint("PUT", "/api/v1/campaigns", b'{"name":"A"}')
    assert len(one) == 64
