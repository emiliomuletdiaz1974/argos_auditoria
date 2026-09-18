"""ARG-067 · the PDF comes only from the canonical dossier JSON, reproducibly and honestly."""

import json
from typing import Any

import pymupdf  # test-only reader (development dependency); never shipped
import pytest

from argos_evidence.core.integrity import file_digest, seal_document
from argos_evidence.dossier import (
    ASSISTED_MARK,
    DossierError,
    qr_payload,
    render_pdf,
)

URL = "https://verify.argos.example/check"
CAMPAIGN = "0199a000-0000-7000-8000-000000000001"


def _dossier(texts: list[dict[str, Any]] | None = None) -> bytes:
    return seal_document(
        {
            "schema": "argos/dossier/1",
            "campaign": {
                "id": CAMPAIGN,
                "name": "Campaña de demostración",
                "status": "sealed",
                "seal": "5" * 64,
                "sealed_at": "2026-09-18T10:00:00.000000Z",
                "library_version": "1.0.0",
                "ontology_version": "1.0.0",
            },
            "results": {
                "units": 17,
                "by_result": {
                    "compliant": 11,
                    "non_compliant": 4,
                    "not_demonstrated": 1,
                    "inconclusive": 1,
                },
            },
            "results_by_obligation": [
                {
                    "obligation": "OBL-RGPD-32-3",
                    "compliant": 3,
                    "non_compliant": 2,
                    "not_demonstrated": 0,
                    "inconclusive": 0,
                },
            ],
            "approvals": [
                {
                    "gate": "launch",
                    "approved_by": "user:dpo",
                    "approved_at": "2026-09-18T09:00:00.000000Z",
                }
            ],
            "findings": [
                {
                    "id": "f1",
                    "challenge_id": "sec-tls",
                    "obligation": "OBL-RGPD-32-3",
                    "severity": "high",
                    "status": "open",
                    "occurrences": 2,
                },
            ],
            "texts": texts
            if texts is not None
            else [
                {
                    "kind": "summary",
                    "finding_id": None,
                    "generated": True,
                    "prompt_sha256": "p" * 64,
                    "body": {
                        "sections": [{"title": "Resumen", "body": "Texto redactado de prueba."}],
                        "verdict_ids": [],
                    },
                },
            ],
            "evidence_chain": {
                "artifacts": [
                    {"verdict_id": "v1", "key": "k", "version_id": "1", "sha256": "a" * 64}
                ],
                "merkle": {
                    "root": "r" * 64,
                    "leaf_count": 1,
                    "leaf_order": "verdict_id",
                    "tree_key": "t",
                },
                "signature": {
                    "key": "s",
                    "version_id": "1",
                    "sha256": "b" * 64,
                    "key_id": "c" * 32,
                    "non_production": True,
                },
                "time_stamp": {
                    "status": "queued",
                    "gen_time": None,
                    "policy": None,
                    "token_key": None,
                },
                "journal_report": None,
            },
        }
    )


def _text(pdf: bytes) -> list[str]:
    with pymupdf.open(stream=pdf, filetype="pdf") as document:  # type: ignore[no-untyped-call]
        return [page.get_text() for page in document]


def test_the_same_dossier_always_gives_the_same_pdf() -> None:
    assert render_pdf(_dossier(), URL) == render_pdf(_dossier(), URL)


def test_every_page_carries_the_dossier_hash() -> None:
    dossier = _dossier()
    pages = _text(render_pdf(dossier, URL))
    assert len(pages) >= 1
    for page in pages:
        assert file_digest(dossier) in page.replace("\n", "")


def test_the_qr_points_to_the_public_verifier_with_the_hash() -> None:
    dossier = _dossier()
    payload = qr_payload(URL, file_digest(dossier))
    assert payload == f"{URL}?dossier={file_digest(dossier)}"
    assert URL in "".join(_text(render_pdf(dossier, URL)))


def test_every_assisted_text_carries_its_mark() -> None:
    texts: list[dict[str, Any]] = [
        {
            "kind": "summary",
            "finding_id": None,
            "generated": True,
            "prompt_sha256": "p" * 64,
            "body": {
                "sections": [
                    {"title": "Uno", "body": "Primero."},
                    {"title": "Dos", "body": "Segundo."},
                ],
                "verdict_ids": [],
            },
        },
        {
            "kind": "finding",
            "finding_id": "f1",
            "generated": True,
            "prompt_sha256": "q" * 64,
            "body": {
                "context": "Contexto.",
                "impact": "Impacto.",
                "recommendation": "Hacer.",
                "verdict_id": "v1",
            },
        },
    ]
    content = "".join(_text(render_pdf(_dossier(texts), URL))).replace("\n", " ")
    assert content.count(ASSISTED_MARK) == 2
    assert "Primero." in content and "Recomendación" in content
    assert ASSISTED_MARK not in "".join(_text(render_pdf(_dossier([]), URL)))


def test_the_figures_are_the_ones_of_the_json() -> None:
    content = "".join(_text(render_pdf(_dossier(), URL))).replace("\n", " ")
    for figure in ("17", "11", "4", "OBL-RGPD-32-3", "sec-tls"):
        assert figure in content


def test_a_dossier_whose_hash_does_not_match_is_not_rendered() -> None:
    tampered = json.loads(_dossier())
    tampered["results"]["units"] = 18
    body = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    with pytest.raises(DossierError, match="hash"):
        render_pdf(body, URL)


def test_a_development_signature_is_shown_as_such() -> None:
    content = "".join(_text(render_pdf(_dossier(), URL)))
    assert "no producción" in content
    assert "sello en cola" in content.lower()
