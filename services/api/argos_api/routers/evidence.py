"""Evidence: the chain of a campaign, its artifacts and its dossier, shown as it is (ARG-077).

Nothing is prettified on the way: a signature made with a development key carries its
`non_production` mark, and a time stamp still in the queue says `queued`. Downloading the dossier
or the bundle is reading, but it is reading the file a supervisor will be handed, so the journal
keeps who took which one.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller, database
from argos_api.paging import Page, Paging, paginate
from argos_common.journal_pg import PostgresJournal
from argos_evidence.activities import EvidenceActivities
from argos_evidence.reads import (
    artifact_with_proof,
    campaign_artifacts,
    campaign_journal_entry,
    current_dossier,
    evidence_chain,
)

router = APIRouter(prefix="/evidence", tags=["evidence"], route_class=CoreRoute)
DOWNLOAD = "evidence.download"
DOSSIER_HEADER = "X-Dossier-Sha256"


def evidence_of(request: Request) -> EvidenceActivities:
    evidence: EvidenceActivities | None = getattr(request.app.state, "evidence", None)
    if evidence is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no evidence service attached")
    return evidence


def _dossier_or_404(dsn: str, campaign_id: UUID) -> dict[str, Any]:
    dossier = current_dossier(dsn, str(campaign_id))
    if dossier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} has no dossier yet")
    return dossier


def _record_download(request: Request, campaign_id: UUID, sha256: str, what: str) -> None:
    PostgresJournal(database(request)).append(
        caller(request).actor,
        DOWNLOAD,
        {"campaign": str(campaign_id), "dossier_sha256": sha256, "format": what},
    )


@router.get(
    "/{campaign_id}/chain",
    summary="State of every link of the evidence chain",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def chain(request: Request, campaign_id: UUID) -> dict[str, Any]:
    evidence = evidence_of(request)
    found: dict[str, Any] = evidence_chain(database(request), evidence.store, str(campaign_id))
    return found


@router.get(
    "/{campaign_id}/artifacts",
    summary="Artifacts of the campaign",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def artifacts(request: Request, campaign_id: UUID, paging: Paging) -> Page:
    rows = campaign_artifacts(
        database(request), str(campaign_id), paging.limit + 1, paging.position
    )
    return paginate(rows, paging.limit)


@router.get(
    "/{campaign_id}/journal/{seq}",
    summary="Journal entry cited by a verdict of the campaign",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def journal_entry(request: Request, campaign_id: UUID, seq: int) -> dict[str, Any]:
    found = campaign_journal_entry(database(request), str(campaign_id), seq)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no verdict of campaign {campaign_id} cites entry {seq}"
        )
    return found


@router.get(
    "/artifacts/{verdict_id}",
    summary="Artifact of a verdict with its inclusion proof",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def artifact(request: Request, verdict_id: UUID) -> dict[str, Any]:
    evidence = evidence_of(request)
    found = artifact_with_proof(database(request), evidence.store, str(verdict_id))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no artifact for verdict {verdict_id}")
    return found


@router.get(
    "/{campaign_id}/dossier.json",
    summary="Campaign dossier, canonical JSON",
    dependencies=[Depends(require_perm("evidence.read"))],
)
def dossier_json(request: Request, campaign_id: UUID) -> Response:
    evidence = evidence_of(request)
    dossier = _dossier_or_404(database(request), campaign_id)
    body = evidence.stored(str(dossier["json_key"]), str(dossier["json_version_id"]))
    _record_download(request, campaign_id, str(dossier["sha256"]), "json")
    # The exact stored bytes: re-serialising them would change the hash the credential cites.
    return Response(
        body, media_type="application/json", headers={DOSSIER_HEADER: dossier["sha256"]}
    )


@router.get(
    "/{campaign_id}/dossier.pdf",
    summary="Campaign dossier, PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "the dossier"}},
    dependencies=[Depends(require_perm("evidence.read"))],
)
def dossier_pdf(request: Request, campaign_id: UUID) -> Response:
    evidence = evidence_of(request)
    dossier = _dossier_or_404(database(request), campaign_id)
    body = evidence.stored(str(dossier["pdf_key"]), str(dossier["pdf_version_id"]))
    _record_download(request, campaign_id, str(dossier["sha256"]), "pdf")
    return Response(body, media_type="application/pdf", headers={DOSSIER_HEADER: dossier["sha256"]})


@router.get(
    "/{campaign_id}/bundle",
    summary="Portable bundle for the public verifier",
    dependencies=[Depends(require_perm("evidence.read"))],
)
async def bundle(request: Request, campaign_id: UUID) -> Response:
    evidence = evidence_of(request)
    dossier = await asyncio.to_thread(_dossier_or_404, database(request), campaign_id)
    exported = await asyncio.to_thread(evidence.bundle, str(dossier["sha256"]))
    await asyncio.to_thread(
        _record_download, request, campaign_id, str(dossier["sha256"]), "bundle"
    )
    return Response(
        json.dumps(exported, ensure_ascii=False),
        media_type="application/json",
        headers={DOSSIER_HEADER: dossier["sha256"]},
    )
