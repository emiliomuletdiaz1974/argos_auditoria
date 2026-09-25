"""ARG-098 · the size of this appliance, as the API applies it (F10-08).

The limits live in `argos_common.capacity`; here the API turns a refusal into the answer of the
contract: a `409` whose detail gives the figures and the options.
"""

from fastapi import HTTPException, Request, status

from argos_common.capacity import CapacityExceededError, enforce

SizeLimits = tuple[str, dict[str, int]]


def size_limits(request: Request) -> SizeLimits | None:
    limits: SizeLimits | None = getattr(request.app.state, "size_limits", None)
    return limits


def refuse_beyond(request: Request, dsn: str, dimension: str) -> None:
    """Nothing when there is room, or no size configured; a `409` with the options otherwise."""
    limits = size_limits(request)
    if limits is None:
        return
    try:
        enforce(dsn, limits[0], limits[1], dimension)
    except CapacityExceededError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None
