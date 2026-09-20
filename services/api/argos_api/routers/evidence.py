"""Evidence: the chain of a campaign, its artifacts and its dossier, shown as it is (ARG-077)."""

from typing import Any

from fastapi import APIRouter, Response

from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{campaign_id}/chain", summary="State of every link of the evidence chain")
def chain(campaign_id: str) -> dict[str, Any]:
    pending("the evidence chain")


@router.get("/{campaign_id}/artifacts", summary="Artifacts of the campaign")
def artifacts(campaign_id: str, paging: Paging) -> Page:
    pending("the artifact listing")


@router.get("/artifacts/{verdict_id}", summary="Artifact of a verdict with its inclusion proof")
def artifact(verdict_id: str) -> dict[str, Any]:
    pending("the artifact detail")


@router.get("/{campaign_id}/dossier.json", summary="Campaign dossier, canonical JSON")
def dossier_json(campaign_id: str) -> dict[str, Any]:
    pending("the JSON dossier")


@router.get(
    "/{campaign_id}/dossier.pdf",
    summary="Campaign dossier, PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "the dossier"}},
)
def dossier_pdf(campaign_id: str) -> Response:
    pending("the PDF dossier")


@router.get("/{campaign_id}/bundle", summary="Portable bundle for the public verifier")
def bundle(campaign_id: str) -> dict[str, Any]:
    pending("the verification bundle")
