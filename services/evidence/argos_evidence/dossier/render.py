"""The PDF of the dossier, built only from its canonical JSON (ARG-067, deviation note ARG-067).

ReportLab (BSD) in invariant mode: the same dossier gives the same PDF, byte
for byte. Every page carries the SHA-256 of the JSON, the cover carries a QR
code with the public verifier's address and that hash, and every text drafted
by the model is printed under its mark. Figures come from the JSON and from
nowhere else: the function receives the JSON bytes and checks their own hash
before reading a single field.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from argos_evidence.artifacts import file_digest, verify_artifact
from argos_evidence.dossier.build import DossierError

ASSISTED_MARK = "Texto asistido por IA"
RESULT_LABELS = {
    "compliant": "Conforme",
    "non_compliant": "No conforme",
    "not_demonstrated": "No demostrado",
    "inconclusive": "No concluyente",
}
FINDING_LABELS = (
    ("context", "Contexto"),
    ("impact", "Impacto"),
    ("recommendation", "Recomendación"),
)
CAMPAIGN_STATUS = {"sealed": "Sellada"}
SEVERITY_LABELS = {"critical": "Crítica", "high": "Alta", "medium": "Media", "low": "Baja"}
FINDING_STATUS = {
    "open": "Abierto",
    "in_remediation": "En subsanación",
    "pending_verification": "Pendiente de verificar",
    "closed_compliant": "Cerrado, conforme",
    "reopened": "Reabierto",
    "risk_accepted": "Riesgo aceptado",
}
NAVY = colors.HexColor("#1b2a4a")

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("title", parent=_STYLES["Title"], textColor=NAVY)
_H2 = ParagraphStyle("h2", parent=_STYLES["Heading2"], textColor=NAVY)
_BODY = _STYLES["BodyText"]
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=8, leading=10)
_MARK = ParagraphStyle("mark", parent=_SMALL, textColor=colors.HexColor("#8a5a00"))


def qr_payload(verifier_url: str, dossier_sha256: str) -> str:
    return f"{verifier_url}?dossier={dossier_sha256}"


def _p(text: object, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _table(rows: list[list[object]], widths: list[float] | None = None) -> Table:
    table = Table([[_p(c, _SMALL) for c in row] for row in rows], colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf3")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _qr(payload: str) -> Drawing:
    widget = QrCodeWidget(payload)
    left, bottom, right, top = widget.getBounds()
    size = 38 * mm
    drawing = Drawing(
        size, size, transform=[size / (right - left), 0, 0, size / (top - bottom), 0, 0]
    )
    drawing.add(widget)
    return drawing


def _cover(dossier: dict[str, Any], digest: str, verifier_url: str) -> list[Any]:
    campaign = dossier["campaign"]
    return [
        _p("Expediente de campaña", _TITLE),
        _p(campaign["name"], _H2),
        _table(
            [
                ["Campo", "Valor"],
                ["Campaña", campaign["id"]],
                ["Estado", CAMPAIGN_STATUS.get(campaign["status"], campaign["status"])],
                ["Sellada", campaign.get("sealed_at") or "-"],
                ["Sello de campaña", campaign.get("seal") or "-"],
                ["Biblioteca de retos", campaign.get("library_version") or "-"],
                ["Ontología", campaign.get("ontology_version") or "-"],
            ],
            [45 * mm, 125 * mm],
        ),
        Spacer(1, 6 * mm),
        _p("Verificación", _H2),
        _qr(qr_payload(verifier_url, digest)),
        _p(f"Comprobador público: {verifier_url}", _SMALL),
        _p(
            "Este PDF se genera a partir del expediente en JSON. Lo que se verifica es ese JSON: "
            "su SHA-256 figura al pie de cada página y en el código QR.",
            _SMALL,
        ),
    ]


def _results(dossier: dict[str, Any]) -> list[Any]:
    results = dossier["results"]
    rows: list[list[object]] = [["Resultado", "Unidades"]]
    rows += [[RESULT_LABELS[k], v] for k, v in results["by_result"].items()]
    rows.append(["Total", results["units"]])
    by_obligation: list[list[object]] = [["Obligación", *RESULT_LABELS.values()]]
    by_obligation += [
        [row["obligation"], *(row[k] for k in RESULT_LABELS)]
        for row in dossier["results_by_obligation"]
    ]
    return [
        _p("Resultados", _H2),
        _table(rows, [60 * mm, 30 * mm]),
        Spacer(1, 4 * mm),
        _table(by_obligation),
    ]


def _approvals_and_findings(dossier: dict[str, Any]) -> list[Any]:
    parts: list[Any] = [_p("Aprobaciones", _H2)]
    approvals = dossier["approvals"]
    parts.append(
        _table(
            [["Punto de control", "Aprobado por", "Momento"]]
            + [[a["gate"], a["approved_by"], a["approved_at"]] for a in approvals]
        )
        if approvals
        else _p("Sin aprobaciones registradas.", _SMALL)
    )
    parts.append(_p("Hallazgos", _H2))
    findings = dossier["findings"]
    parts.append(
        _table(
            [["Reto", "Obligación", "Severidad", "Estado", "Ocurrencias"]]
            + [
                [
                    f["challenge_id"],
                    f["obligation"],
                    SEVERITY_LABELS.get(f["severity"], f["severity"]),
                    FINDING_STATUS.get(f["status"], f["status"]),
                    f["occurrences"],
                ]
                for f in findings
            ]
        )
        if findings
        else _p("Sin hallazgos.", _SMALL)
    )
    return parts


def _texts(dossier: dict[str, Any]) -> list[Any]:
    texts = dossier["texts"]
    if not texts:
        return []
    parts: list[Any] = [_p("Textos redactados", _H2)]
    for text in texts:
        parts.append(
            _p(f"{ASSISTED_MARK} · prompt SHA-256 {text['prompt_sha256']}", _MARK)
            if text["generated"]
            else _p("Texto redactado por una persona", _MARK)
        )
        body = text["body"]
        if text["kind"] == "summary":
            for section in body.get("sections", []):
                parts += [_p(section["title"], _STYLES["Heading4"]), _p(section["body"])]
        else:
            parts += [_p(f"{label}: {body.get(key, '')}") for key, label in FINDING_LABELS]
        parts.append(Spacer(1, 3 * mm))
    return parts


def _chain(dossier: dict[str, Any]) -> list[Any]:
    chain = dossier["evidence_chain"]
    merkle, signature = chain["merkle"], chain["signature"]
    stamp, report = chain["time_stamp"], chain["journal_report"]
    if stamp is None:
        stamp_text = "Sin sellar"
    elif stamp["status"] == "stamped":
        stamp_text = f"Sellado el {stamp['gen_time']} (política {stamp['policy']})"
    else:
        stamp_text = "Firmado, sello en cola"
    if signature is None:
        signature_text = "Sin firmar"
    else:
        signature_text = f"Clave {signature['key_id']}" + (
            " (clave de desarrollo, no producción)" if signature["non_production"] else ""
        )
    rows: list[list[object]] = [
        ["Pieza", "Valor"],
        ["Artefactos", len(chain["artifacts"])],
        ["Raíz de Merkle", merkle["root"] if merkle else "-"],
        ["Firma", signature_text],
        ["Sello de tiempo", stamp_text],
        ["Informe del diario", report["sha256"] if report else "Pendiente"],
    ]
    artifacts: list[list[object]] = [["Veredicto", "SHA-256 del artefacto"]]
    artifacts += [[a["verdict_id"], a["sha256"]] for a in chain["artifacts"]]
    return [
        _p("Cadena de evidencia", _H2),
        _table(rows, [40 * mm, 130 * mm]),
        Spacer(1, 4 * mm),
        _table(artifacts, [70 * mm, 100 * mm]),
    ]


def render_pdf(dossier_json: bytes, verifier_url: str) -> bytes:
    """The PDF of a dossier whose own hash checks out."""
    if not verify_artifact(dossier_json):
        raise DossierError("the dossier does not match its own hash: it is not rendered")
    dossier: dict[str, Any] = json.loads(dossier_json)
    digest = file_digest(dossier_json)

    def footer(canvas: Canvas, _: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 10 * mm, f"SHA-256 del expediente: {digest}")
        canvas.drawRightString(195 * mm, 10 * mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        invariant=1,
        title=f"Expediente {dossier['campaign']['id']}",
        author="ARGOS",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        bottomMargin=18 * mm,
    )
    story = [
        *_cover(dossier, digest, verifier_url),
        *_results(dossier),
        *_approvals_and_findings(dossier),
        *_texts(dossier),
        *_chain(dossier),
    ]
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
