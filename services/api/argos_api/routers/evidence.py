"""Evidence: the chain of a campaign, its artifacts and its dossier, shown as it is (ARG-077)."""

from typing import Any

from fastapi import APIRouter, Depends, Response

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/evidence", tags=["evidence"], route_class=CoreRoute)


@router.get(
    "/{campaign_id}/chain",
    summary="State of every link of the evidence chain",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def chain(campaign_id: str) -> dict[str, Any]:
    pending("the evidence chain")


@router.get(
    "/{campaign_id}/artifacts",
    summary="Artifacts of the campaign",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def artifacts(campaign_id: str, paging: Paging) -> Page:
    pending("the artifact listing")


@router.get(
    "/artifacts/{verdict_id}",
    summary="Artifact of a verdict with its inclusion proof",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def artifact(verdict_id: str) -> dict[str, Any]:
    pending("the artifact detail")


@router.get(
    "/{campaign_id}/dossier.json",
    summary="Campaign dossier, canonical JSON",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def dossier_json(campaign_id: str) -> dict[str, Any]:
    pending("the JSON dossier")


@router.get(
    "/{campaign_id}/dossier.pdf",
    summary="Campaign dossier, PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "the dossier"}},
    dependencies=[Depends(require_perm("evidence.read"))],
)
def dossier_pdf(campaign_id: str) -> Response:
    pending("the PDF dossier")


@router.get(
    "/{campaign_id}/bundle",
    summary="Portable bundle for the public verifier",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def bundle(campaign_id: str) -> dict[str, Any]:
    pending("the verification bundle")
