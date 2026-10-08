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


# ---------- read by a person and printed: no IRIs, no account ids, no raw instants ----------

SUB = "473f7bd3-2730-4d40-9e2f-9e70e3e57b92"


def _readable(approvals: list[dict[str, Any]]) -> str:
    dossier = json.loads(_dossier())
    dossier.pop("sha256", None)
    iri = "https://ns.argos.eu/norms/OBL-RGPD-32-3"
    dossier["results_by_obligation"][0]["obligation"] = iri
    dossier["findings"][0]["obligation"] = iri
    dossier["approvals"] = approvals
    pdf = render_pdf(seal_document(dossier), URL)
    return "".join(_text(pdf)).replace("\n", " ")


def test_an_obligation_is_printed_by_its_id_not_by_its_iri() -> None:
    content = _readable([])
    assert "OBL-RGPD-32-3" in content
    assert "ns.argos.eu/norms" not in content


def test_whoever_approved_is_printed_by_name() -> None:
    content = _readable(
        [
            {
                "gate": "start",
                "approved_by": f"user:{SUB}",
                "approver_name": "DPO Synthetic",
                "approved_at": "2026-10-08T03:14:51.485903Z",
            }
        ]
    )
    assert "DPO Synthetic" in content
    assert SUB not in content, "the account id is not for a person to read"
    assert "Inicio de la campaña" in content, "the gate by what it is, not by its code"


def test_an_approval_without_a_name_shows_a_short_id() -> None:
    content = _readable(
        [{"gate": "start", "approved_by": f"user:{SUB}", "approved_at": "2026-10-08T03:14:51Z"}]
    )
    assert "473f7bd3" in content and SUB not in content


def test_instants_are_printed_as_a_person_reads_them() -> None:
    content = _readable(
        [
            {
                "gate": "start",
                "approved_by": f"user:{SUB}",
                "approver_name": "DPO Synthetic",
                "approved_at": "2026-10-08T03:14:51.485903Z",
            }
        ]
    )
    assert "08/10/2026 03:14:51 UTC" in content
    assert "18/09/2026 10:00:00 UTC" in content, "the sealing instant of the cover too"
    assert "2026-10-08T03:14:51" not in content and ".485903" not in content


# ---------- a document for people: what was audited, what to fix, and the technique last ----------

SYSTEM = "01920000-0000-7000-8000-00000000a001"
LABELS = {
    "systems": {SYSTEM: {"name": "historia-clinica", "kind": "rdbms"}},
    "challenges": {"sec-tls": "Cifrado en tránsito exigido por el motor de datos"},
    "obligations": {
        "OBL-RGPD-32-3": {
            "title": "Cifrado en tránsito hacia los sistemas con datos personales",
            "norm": "RGPD",
            "article": "32.1.b",
            "summary": "Las conexiones a los almacenes con datos personales exigen cifrado.",
        }
    },
}


def _for_people(labels: dict[str, Any] | None = LABELS) -> list[str]:
    dossier = json.loads(_dossier())
    dossier.pop("sha256", None)
    dossier["campaign"]["scope"] = {"system_ids": [SYSTEM]}
    finding = dossier["findings"][0]
    dossier["findings"] = [
        finding | {"id": "f1", "system_id": SYSTEM, "element": "public.patients.ssn"},
        finding | {"id": "f2", "system_id": SYSTEM, "element": "public.patients.email"},
    ]
    if labels is not None:
        dossier["labels"] = labels
    return [page.replace("\n", " ") for page in _text(render_pdf(seal_document(dossier), URL))]


def test_the_first_page_says_what_was_audited_and_how_it_went() -> None:
    first = _for_people()[0]
    assert "historia-clinica" in first, "the system audited, by its name"
    assert "Se comprobaron 17 controles" in first
    assert "11 se cumplen" in first and "4 no se cumplen" in first
    assert "2 hallazgos" in first and "1 problema" in first


def test_findings_are_grouped_into_problems_with_their_elements_by_name() -> None:
    content = " ".join(_for_people())
    assert content.count("Cifrado en tránsito exigido por el motor de datos") == 1, "one problem"
    assert "2 elementos afectados" in content
    assert "public.patients.ssn" in content and "public.patients.email" in content
    assert "Cifrado en tránsito hacia los sistemas con datos personales" in content
    assert "RGPD, art. 32.1.b" in content


def test_the_technical_details_go_to_an_annex_at_the_end() -> None:
    pages = _for_people()
    annex = next(i for i, page in enumerate(pages) if "Anexo técnico" in page)
    assert annex == len(pages) - 1 or all("Anexo" not in p for p in pages[annex + 1 :])
    assert "a" * 64 not in " ".join(pages[:annex]), "no artifact hash before the annex"
    assert "a" * 64 in " ".join(pages[annex:]).replace(" ", "")


def test_a_dossier_without_labels_is_still_read_by_its_codes() -> None:
    """A dossier sealed before the labels existed renders the same way, with its codes."""
    content = " ".join(_for_people(labels=None))
    assert "sec-tls" in content and "OBL-RGPD-32-3" in content
    assert "public.patients.ssn" in content
