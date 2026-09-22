"""Inventory: coverage, the graph node and the review queue of the classifier (ARG-074).

The queue is where a person decides what a model only proposed. Resolving it here writes the human
edge in the graph, the entry in the journal and the label the calibration of ARG-055 learns from:
one call, and the three places that have to know about it.
"""

from typing import Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller, database
from argos_api.paging import Page, Paging, paginate
from argos_inventory.catalog.views import coverage as catalog_coverage
from argos_inventory.catalog.views import freshness, pending_review_by_system
from argos_inventory.classify.assisted import decide_review, pending_reviews
from argos_inventory.graph.model import CATEGORIES
from argos_inventory.graph.reads import node_detail
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.deltas import node_deltas

router = APIRouter(prefix="/inventory", tags=["inventory"], route_class=CoreRoute)
MAX_NEIGHBOURS = 200
ALREADY_DECIDED = "already decided"


class ReviewDecision(BaseModel):
    """What a DPO reviewer decides about a column the classifier could not settle."""

    decision: Literal["accept", "reject", "correct"] = Field(
        description=(
            "accept confirms the proposed category; reject leaves the column unclassified; "
            "correct rejects the proposal and classifies the column as `category`"
        )
    )
    category: str | None = Field(default=None, description="only when correcting")
    note: str = ""

    @model_validator(mode="after")
    def _a_correction_names_a_category(self) -> Self:
        if self.decision == "correct" and self.category not in CATEGORIES:
            raise ValueError(f"a correction needs a category: one of {list(CATEGORIES)}")
        return self


@router.get(
    "/coverage",
    summary="Coverage, freshness and pending review of the inventory",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def coverage(request: Request) -> dict[str, Any]:
    dsn = database(request)
    pending = pending_review_by_system(dsn)
    fresh = {str(row["system_id"]): row for row in freshness(dsn)}
    systems = []
    for row in catalog_coverage(dsn):
        system_id = str(row["system_id"])
        seen = fresh.get(system_id, {})
        systems.append(
            {
                **{key: _plain(value) for key, value in row.items()},
                "system_id": system_id,
                "pending_review": pending.get(system_id, 0),
                "last_scan_at": _plain(seen.get("last_scan_at")),
                "last_scan_status": seen.get("last_scan_status"),
                "hours_since_scan": _plain(seen.get("hours_since_scan")),
                "missing_assets": seen.get("missing_assets", 0),
                "has_owner": seen.get("has_owner", False),
            }
        )
    return {
        "systems": systems,
        "pending_review": sum(pending.values()),
        "special_columns": sum(int(s.get("special_columns") or 0) for s in systems),
        "missing_assets": sum(int(s.get("missing_assets") or 0) for s in systems),
    }


@router.get(
    "/nodes/{node_key}",
    summary="A node of the inventory graph",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def node(
    request: Request,
    node_key: str,
    limit: int = Query(50, ge=1, le=MAX_NEIGHBOURS, description="neighbours to return"),
) -> dict[str, Any]:
    dsn = database(request)
    detail = node_detail(GraphStore(dsn), node_key, limit)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no node with key {node_key}")
    return {**detail, "deltas": node_deltas(dsn, node_key)}


@router.get(
    "/review-queue",
    summary="Columns awaiting human review",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def review_queue(request: Request, paging: Paging) -> Page:
    rows = pending_reviews(database(request), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)


@router.post(
    "/review-queue/{node_key}",
    summary="Decide about a column under review",
    dependencies=[Depends(require_perm("inventory.review"))],
)
def review(request: Request, node_key: str, body: ReviewDecision) -> dict[str, Any]:
    dsn = database(request)
    try:
        decided = decide_review(
            GraphStore(dsn),
            dsn,
            node_key,
            body.decision == "accept",
            caller(request).actor,
            corrected_to=body.category if body.decision == "correct" else None,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no review for {node_key}") from None
    except ValueError as clash:
        if ALREADY_DECIDED in str(clash):
            raise HTTPException(status.HTTP_409_CONFLICT, str(clash)) from None
        raise
    answer: dict[str, Any] = {"node_key": node_key, "status": decided}
    if body.decision == "correct":
        answer["corrected_to"] = body.category
    return answer


def _plain(value: Any) -> Any:
    """Whatever PostgreSQL returned, in something JSON can carry."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
