"""ARG-098 · the size of this appliance, as the API applies it (F10-08).

The limits live in `argos_common.capacity`; here the API turns a refusal into the answer of the
contract: a `409` whose detail gives the figures and the options.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import HTTPException, Request, status

from argos_common import capacity
from argos_common.capacity import LOCK_SQL, CapacityExceededError, lock_key

SizeLimits = tuple[str, dict[str, int]]


def size_limits(request: Request) -> SizeLimits | None:
    limits: SizeLimits | None = getattr(request.app.state, "size_limits", None)
    return limits


def _reserve(
    conn: psycopg.Connection[Any], request: Request, dsn: str, dimension: str, holds_place: bool
) -> None:
    limits = size_limits(request)
    if limits is None or holds_place:
        return
    conn.execute(LOCK_SQL, (lock_key(dimension),))
    try:
        capacity.enforce(dsn, limits[0], limits[1], dimension)
    except CapacityExceededError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None


@asynccontextmanager
async def within_size(
    request: Request, dsn: str, dimension: str, holds_place: bool = False
) -> AsyncIterator[psycopg.Connection[Any]]:
    """Measure and act as one step: the lock of the dimension is held until the act commits, so
    two requests at once cannot both see the last place (quality review QA-006, QA-061).

    What the act writes on the connection it receives commits with it; `holds_place` skips the
    measure for what already counts (launching again a campaign that runs).
    """
    conn: psycopg.Connection[Any] = await asyncio.to_thread(lambda: psycopg.connect(dsn))
    try:
        await asyncio.to_thread(_reserve, conn, request, dsn, dimension, holds_place)
        yield conn
        await asyncio.to_thread(conn.commit)
    except BaseException:
        await asyncio.to_thread(conn.rollback)
        raise
    finally:
        await asyncio.to_thread(conn.close)
