"""Inventory: coverage, the graph node and the review queue of the classifier (ARG-074)."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/inventory", tags=["inventory"])


class ReviewDecision(BaseModel):
    """What a DPO reviewer decides about a column the classifier could not settle."""

    decision: str = Field(description="accept, reject or reclassify")
    category: str | None = Field(default=None, description="category when reclassifying")
    note: str = ""


@router.get(
    "/coverage",
    summary="Coverage, freshness and pending review of the inventory",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def coverage() -> dict[str, Any]:
    pending("inventory coverage")


@router.get(
    "/nodes/{node_key}",
    summary="A node of the inventory graph",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def node(node_key: str) -> dict[str, Any]:
    pending("the inventory node")


@router.get(
    "/review-queue",
    summary="Columns awaiting human review",
    dependencies=[Depends(require_perm("inventory.read"))],
)
def review_queue(paging: Paging) -> Page:
    pending("the review queue")


@router.post(
    "/review-queue/{node_key}",
    summary="Decide about a column under review",
    dependencies=[Depends(require_perm("inventory.review"))],
)
def review(node_key: str, body: ReviewDecision) -> dict[str, Any]:
    pending("the review decision")
