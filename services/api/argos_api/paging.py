"""ARG-071 · pagination by opaque cursor, never by offset.

An offset lies while the data moves: a row inserted between two pages pushes another one out of
sight, and a listing of findings that silently skips one is worse than no listing at all. The cursor
points at a place in the order (`created_at`, `id`), so the next page starts exactly where the
previous one ended, whatever happened in between. It is opaque on purpose: what it carries is ours
to change, and nobody should build a query out of it.
"""

import base64
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

CURSOR_VERSION = 1
DEFAULT_PAGE = 50
MAX_PAGE = 200
AT = "created_at"
ID = "id"

Row = Mapping[str, Any]


class CursorError(ValueError):
    """The cursor did not come from here, or it no longer means anything."""


def cursor_for(at: str, ident: str) -> str:
    raw = json.dumps([CURSOR_VERSION, at, ident], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def position_of(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        version, at, ident = json.loads(base64.urlsafe_b64decode(padded))
    except Exception as broken:  # any malformed cursor is the same mistake
        raise CursorError("the cursor is not one of ours") from broken
    if version != CURSOR_VERSION or not isinstance(at, str) or not isinstance(ident, str):
        raise CursorError("the cursor is not one of ours")
    return at, ident


def apply_keyset(
    rows: Iterable[Row], position: tuple[str, str] | None, at: str = AT, ident: str = ID
) -> list[Row]:
    """The rows strictly after `position` in the order the listings use.

    Listings sort by a key descending (the instant, unless a listing has a better order, like the
    findings, worst first) and, for the same key, by identifier descending. This is the in-memory
    twin of the SQL predicate `(key, id) < (%s, %s)`, and the two must agree.
    """
    ordered = sorted(rows, key=lambda row: (str(row[at]), str(row[ident])), reverse=True)
    if position is None:
        return ordered
    return [row for row in ordered if (str(row[at]), str(row[ident])) < position]


class Page(BaseModel):
    """A page of a listing: the items and the cursor to ask for the next one."""

    items: list[dict[str, Any]] = Field(default_factory=list)
    next: str | None = Field(default=None, description="cursor of the next page, null at the end")


class PageRequest(BaseModel):
    """What the client asked for, with the cursor already checked."""

    cursor: str | None = None
    limit: int = DEFAULT_PAGE

    @property
    def position(self) -> tuple[str, str] | None:
        return position_of(self.cursor)


def page_request(
    cursor: Annotated[
        str | None, Query(description="opaque cursor returned by the previous page")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE, description="items per page")] = DEFAULT_PAGE,
) -> PageRequest:
    try:
        position_of(cursor)
    except CursorError as broken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(broken)) from None
    return PageRequest(cursor=cursor, limit=limit)


Paging = Annotated[PageRequest, Depends(page_request)]


def paginate(rows: Sequence[Row], limit: int, at: str = AT, ident: str = ID) -> Page:
    """The first `limit` rows in listing order, plus the cursor of the last one."""
    ordered = apply_keyset(rows, None, at, ident)
    items = [dict(row) for row in ordered[:limit]]
    if len(ordered) <= limit or not items:
        return Page(items=items)
    last = items[-1]
    return Page(items=items, next=cursor_for(str(last[at]), str(last[ident])))
