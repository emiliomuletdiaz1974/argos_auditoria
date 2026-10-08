"""The PDF of the dossier, built only from its canonical JSON (ARG-067, deviation note ARG-067).

ReportLab (BSD) in invariant mode: the same dossier gives the same PDF, byte
for byte. Every page carries the SHA-256 of the JSON, the first page carries a
QR code with the public verifier's address and that hash, and every text
drafted by the model is printed under its mark. Figures come from the JSON and
from nowhere else: the function receives the JSON bytes and checks their own
hash before reading a single field.

It is a document for people, read and printed: first what was audited and how
it went, then what has to be fixed (the findings grouped into problems, with
the elements affected by name), then the result per obligation, and the
technique (hashes, signature, stamp, artifacts) in an annex at the end. Names
and titles come from the `labels` of the JSON; a dossier sealed before they
existed is read by its codes.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from argos_evidence.core.integrity import file_digest, verify_artifact
from argos_evidence.dossier.build import DossierError

ASSISTED_MARK = "Texto asistido por IA"
NORMS = "https://ns.argos.eu/norms/"
FINDING_LABELS = (
    ("context", "Contexto"),
    ("impact", "Impacto"),
    ("recommendation", "Recomendación"),
)
GATE_LABELS = {"start": "Inicio de la campaña", "sampling": "Muestreo (doble control)"}
NORM_NAMES = {"AIACT": "Reglamento de IA", "EHDS": "EEDS", "SELF": "Especificación de ARGOS"}
KIND_NAMES = {
    "rdbms": "base de datos",
    "files": "ficheros",
    "api": "API",
    "directory": "directorio",
    "clinical": "sistema clínico",
    "ai": "sistema de IA",
}
SEVERITY_ORDER = ("critical", "high", "medium", "low")
FINDING_STATUS = {
    "open": ("abierto", "abiertos"),
    "in_remediation": ("en subsanación", "en subsanación"),
    "pending_verification": ("pendiente de verificar", "pendientes de verificar"),
    "closed_compliant": ("cerrado y conforme", "cerrados y conformes"),
    "reopened": ("reabierto", "reabiertos"),
    "risk_accepted": ("con el riesgo aceptado", "con el riesgo aceptado"),
}
# How many elements of one problem are named; the rest are counted.
ELEMENTS_SHOWN = 25

NAVY = colors.HexColor("#1b2a4a")
MUTED = colors.HexColor("#5b6475")
_NOTE = "<br/><font size=8 color='#5b6475'>{}</font>"
LINE = colors.HexColor("#d9dee7")
SOFT = colors.HexColor("#f3f5f9")
RESULT = {
    "compliant": ("Se cumple", "se cumplen", colors.HexColor("#067647")),
    "non_compliant": ("No se cumple", "no se cumplen", colors.HexColor("#b42318")),
    "inconclusive": ("No concluyente", "no son concluyentes", colors.HexColor("#b54708")),
    "not_demonstrated": ("No demostrado", "no se han podido demostrar", colors.HexColor("#667085")),
}
SEVERITY = {
    "critical": ("Crítica", colors.HexColor("#b42318")),
    "high": ("Alta", colors.HexColor("#b54708")),
    "medium": ("Media", colors.HexColor("#667085")),
    "low": ("Baja", colors.HexColor("#667085")),
}

_STYLES = getSampleStyleSheet()
_BODY = ParagraphStyle("body", parent=_STYLES["BodyText"], fontSize=10, leading=14)
_LEAD = ParagraphStyle("lead", parent=_BODY, fontSize=11.5, leading=16)
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=8.5, leading=11, textColor=MUTED)
_CODE = ParagraphStyle("code", parent=_BODY, fontName="Courier", fontSize=6.8, leading=8.5)
_KICKER = ParagraphStyle("kicker", parent=_SMALL, fontSize=9, spaceAfter=2)
_TITLE = ParagraphStyle(
    "title", parent=_STYLES["Title"], textColor=NAVY, fontSize=22, leading=27, alignment=0
)
# A heading never stays alone at the foot of a page.
_H2 = ParagraphStyle(
    "h2", parent=_STYLES["Heading2"], textColor=NAVY, spaceBefore=10, keepWithNext=1
)
_H3 = ParagraphStyle("h3", parent=_STYLES["Heading4"], textColor=NAVY, spaceBefore=6)
_MARK = ParagraphStyle("mark", parent=_SMALL, textColor=colors.HexColor("#8a5a00"))


def qr_payload(verifier_url: str, dossier_sha256: str) -> str:
    return f"{verifier_url}?dossier={dossier_sha256}"


def _hex(colour: colors.Color) -> str:
    return f"#{colour.hexval()[2:]}"


def _short(obligation: object) -> str:
    return str(obligation).removeprefix(NORMS)


def _instant(value: object) -> str:
    if not value:
        return "-"
    try:
        moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return moment.astimezone(dt.UTC).strftime("%d/%m/%Y %H:%M:%S UTC")


def _approver(approval: dict[str, Any]) -> str:
    """The name the person had when approving; a short id for approvals recorded without one."""
    if approval.get("approver_name"):
        return str(approval["approver_name"])
    kind, _, account = str(approval["approved_by"]).partition(":")
    return f"cuenta {account[:8]}…" if account else kind


def _p(text: object, style: ParagraphStyle = _BODY) -> Paragraph:
    """Plain text: whatever comes from the JSON is escaped."""
    return Paragraph(escape(str(text)), style)


def _m(markup: str, style: ParagraphStyle = _BODY) -> Paragraph:
    """Markup written here, around values already escaped."""
    return Paragraph(markup, style)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _table(rows: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(style))
    return table


def _qr(payload: str, size: float = 30 * mm) -> Drawing:
    widget = QrCodeWidget(payload)
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(
        size, size, transform=[size / (right - left), 0, 0, size / (top - bottom), 0, 0]
    )
    drawing.add(widget)
    return drawing


def _bar(by_result: dict[str, int], total: int, width: float = 170 * mm) -> Drawing:
    height = 7 * mm
    drawing = Drawing(width, height)
    x = 0.0
    for key in RESULT:
        count = int(by_result.get(key, 0))
        if not count or not total:
            continue
        part = width * count / total
        colour = RESULT[key][2]
        drawing.add(Rect(x, 0, part, height, fillColor=colour, strokeColor=colors.white))
        if part > 10 * mm:
            drawing.add(
                String(x + 3, height / 2 - 3, str(count), fillColor=colors.white, fontSize=8)
            )
        x += part
    return drawing


class _Labels:
    """The names the JSON carries for its codes, and the code itself when it carries none."""

    def __init__(self, dossier: dict[str, Any]) -> None:
        labels = dossier.get("labels") or {}
        self.systems: dict[str, Any] = labels.get("systems") or {}
        self.challenges: dict[str, str] = labels.get("challenges") or {}
        self.obligations: dict[str, Any] = labels.get("obligations") or {}

    def system(self, system_id: str) -> str:
        found = self.systems.get(system_id)
        if not found:
            return system_id
        kind = KIND_NAMES.get(str(found.get("kind")), "")
        return f"{found['name']} ({kind})" if kind else str(found["name"])

    def challenge(self, challenge_id: str) -> str:
        return str(self.challenges.get(challenge_id) or challenge_id)

    def obligation(self, obligation: object) -> tuple[str, str]:
        """Its title, and where it comes from: norm, article and id."""
        code = _short(obligation)
        found = self.obligations.get(code)
        if not found:
            return code, ""
        norm = NORM_NAMES.get(str(found["norm"]), str(found["norm"]))
        return str(found["title"]), f"{norm}, art. {found['article']} · {code}"

    def summary(self, obligation: object) -> str:
        found = self.obligations.get(_short(obligation)) or {}
        return str(found.get("summary") or "")


def _first_page(dossier: dict[str, Any], labels: _Labels, digest: str, url: str) -> list[Any]:
    campaign, results = dossier["campaign"], dossier["results"]
    by, total = results["by_result"], int(results["units"])
    systems = [labels.system(s) for s in (campaign.get("scope") or {}).get("system_ids", [])]
    findings = dossier["findings"]
    problems = {(f["challenge_id"], _short(f["obligation"])) for f in findings}
    severities = Counter(f["severity"] for f in findings)
    outcome = [
        f"<font color='{_hex(RESULT[k][2])}'><b>{by[k]} {RESULT[k][1]}</b></font>"
        for k in RESULT
        if by.get(k)
    ]
    outcome_text = (
        ", ".join(outcome[:-1]) + " y " + outcome[-1] if len(outcome) > 1 else "".join(outcome)
    )
    gravity = [
        _plural(severities[s], SEVERITY[s][0].lower(), SEVERITY[s][0].lower() + "s")
        for s in SEVERITY_ORDER
        if severities.get(s)
    ]
    summary = f"Se comprobaron <b>{total} controles</b>"
    if systems:
        summary += f" sobre {_plural(len(systems), 'sistema', 'sistemas')}"
    summary += f": {outcome_text}." if outcome else "."
    if findings:
        summary += (
            f" De ahí salen <b>{_plural(len(findings), 'hallazgo', 'hallazgos')}</b> en "
            f"{_plural(len(problems), 'problema', 'problemas distintos')}"
            + (f" ({', '.join(gravity)})" if gravity else "")
            + "."
        )
    else:
        summary += " No hay hallazgos."
    audited = escape(", ".join(systems)) if systems else "los del alcance de la campaña"
    parts: list[Any] = [
        _m("EXPEDIENTE DE AUDITORÍA DE CUMPLIMIENTO · ARGOS", _KICKER),
        _p(campaign["name"], _TITLE),
        _m(
            f"Sistemas auditados: <b>{audited}</b><br/>"
            f"Campaña sellada el <b>{escape(_instant(campaign.get('sealed_at')))}</b>",
            _LEAD,
        ),
        Spacer(1, 5 * mm),
        _m("Resumen", _H2),
        _m(summary, _LEAD),
        Spacer(1, 3 * mm),
        _bar(by, total),
        _m(
            " &nbsp; ".join(
                f"<font color='{_hex(RESULT[k][2])}'>■</font> {RESULT[k][0]}" for k in RESULT
            ),
            _SMALL,
        ),
        _m("Quién la autorizó", _H2),
    ]
    approvals = dossier["approvals"]
    if approvals:
        rows: list[list[Any]] = [
            [_m("Punto de control", _SMALL), _m("Aprobado por", _SMALL), _m("Momento", _SMALL)]
        ]
        rows += [
            [
                _p(GATE_LABELS.get(a["gate"], a["gate"])),
                _p(_approver(a)),
                _p(_instant(a["approved_at"])),
            ]
            for a in approvals
        ]
        parts.append(_table(rows, [55 * mm, 60 * mm, 55 * mm]))
    else:
        parts.append(_p("Sin aprobaciones registradas.", _SMALL))
    check = _m(
        "<b>¿Este documento es auténtico?</b><br/>Escanea el código o visita "
        f"{escape(url)}. Este PDF presenta el expediente firmado; lo que se comprueba es el "
        "expediente en JSON, cuya huella SHA-256 figura al pie de cada página y en el código "
        "QR. Los detalles técnicos están en el anexo.",
    )
    box = Table([[_qr(qr_payload(url, digest)), check]], colWidths=(36 * mm, 134 * mm))
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [*parts, Spacer(1, 6 * mm), box, PageBreak()]


def _problems(dossier: dict[str, Any], labels: _Labels) -> list[Any]:
    findings = dossier["findings"]
    if not findings:
        return [_m("Qué hay que corregir", _H2), _p("Sin hallazgos.", _SMALL)]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        groups[(f["challenge_id"], _short(f["obligation"]), f["severity"])].append(f)
    ranked = sorted(
        groups.items(),
        key=lambda item: (SEVERITY_ORDER.index(item[0][2]), -len(item[1]), item[0][0], item[0][1]),
    )
    parts: list[Any] = [
        _m("Qué hay que corregir", _H2),
        _p(
            "Cada problema reúne los hallazgos del mismo control sobre la misma obligación, del "
            "más grave al menos grave.",
            _SMALL,
        ),
    ]
    for (challenge, obligation, severity), items in ranked:
        name, colour = SEVERITY[severity]
        title, source = labels.obligation(obligation)
        statuses = Counter(f["status"] for f in items)
        state = ", ".join(
            f"{n} {FINDING_STATUS.get(s, (s, s))[0 if n == 1 else 1]}"
            for s, n in sorted(statuses.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        affected = _plural(len(items), "elemento afectado", "elementos afectados")
        block: list[Any] = [
            _m(
                f"<font color='{_hex(colour)}'>● {name.upper()}</font> &nbsp; "
                f"{escape(labels.challenge(challenge))}",
                _H3,
            ),
            _m(
                f"{affected} ({escape(state)}). Incumple <i>{escape(title)}</i>"
                + (f" ({escape(source)})" if source else "")
                + "."
            ),
        ]
        if labels.summary(obligation):
            block.append(_p(labels.summary(obligation), _SMALL))
        elements = sorted({str(f["element"]) for f in items if f.get("element")})
        if elements:
            shown = ", ".join(escape(e) for e in elements[:ELEMENTS_SHOWN])
            rest = len(elements) - ELEMENTS_SHOWN
            block.append(
                _m(
                    f"<b>Dónde:</b> <font name='Courier' size='8'>{shown}</font>"
                    + (f" y {rest} más" if rest > 0 else ""),
                    _SMALL,
                )
            )
        parts.append(KeepTogether([*block, Spacer(1, 3 * mm)]))
    return parts


def _by_obligation(dossier: dict[str, Any], labels: _Labels) -> list[Any]:
    rows: list[list[Any]] = [
        [_m("Obligación", _SMALL), _m("Resultado", _SMALL), _m("Pruebas", _SMALL)]
    ]
    ordered = sorted(
        dossier["results_by_obligation"],
        key=lambda r: (-r["non_compliant"], -r["inconclusive"], _short(r["obligation"])),
    )
    for row in ordered:
        title, source = labels.obligation(row["obligation"])
        worst = next(
            (k for k in ("non_compliant", "inconclusive", "not_demonstrated") if row[k]),
            "compliant",
        )
        word, _, colour = RESULT[worst]
        detail = ", ".join(f"{row[k]} {RESULT[k][0].lower()}" for k in RESULT if row[k])
        rows.append(
            [
                _m(
                    f"<b>{escape(title)}</b>"
                    + (
                        f"<br/><font size=8 color='#5b6475'>{escape(source)}</font>"
                        if source
                        else ""
                    )
                ),
                _m(
                    f"<font color='{_hex(colour)}'><b>{word}</b></font>"
                    + _NOTE.format(escape(detail))
                ),
                _p(sum(int(row[k]) for k in RESULT)),
            ]
        )
    return [_m("Resultado por obligación", _H2), _table(rows, [108 * mm, 44 * mm, 18 * mm])]


def _texts(dossier: dict[str, Any]) -> list[Any]:
    texts = dossier["texts"]
    if not texts:
        return []
    parts: list[Any] = [_m("Textos redactados", _H2)]
    for text in texts:
        parts.append(
            _p(f"{ASSISTED_MARK} · prompt SHA-256 {text['prompt_sha256']}", _MARK)
            if text["generated"]
            else _p("Texto redactado por una persona", _MARK)
        )
        body = text["body"]
        if text["kind"] == "summary":
            for section in body.get("sections", []):
                parts += [_p(section["title"], _H3), _p(section["body"])]
        else:
            parts += [_p(f"{label}: {body.get(key, '')}") for key, label in FINDING_LABELS]
        parts.append(Spacer(1, 3 * mm))
    return parts


def _annex(dossier: dict[str, Any], digest: str) -> list[Any]:
    campaign, chain = dossier["campaign"], dossier["evidence_chain"]
    merkle, signature = chain["merkle"], chain["signature"]
    stamp, report = chain["time_stamp"], chain["journal_report"]
    if stamp is None:
        stamp_text = "Sin sellar"
    elif stamp["status"] == "stamped":
        stamp_text = f"Sellado el {_instant(stamp['gen_time'])} (política {stamp['policy']})"
    else:
        stamp_text = "Firmado, sello en cola"
    if signature is None:
        signature_text = "Sin firmar"
    else:
        signature_text = f"Clave {signature['key_id']}" + (
            " (clave de desarrollo, no producción)" if signature["non_production"] else ""
        )
    facts = [
        ("Campaña", campaign["id"]),
        ("Huella del expediente (SHA-256)", digest),
        ("Sello de campaña", campaign.get("seal") or "-"),
        (
            "Raíz de Merkle",
            f"{merkle['root']} ({merkle['leaf_count']} artefactos)" if merkle else "-",
        ),
        ("Firma", signature_text),
        ("Sello de tiempo", stamp_text),
        ("Informe del diario", report["sha256"] if report else "Pendiente"),
        ("Biblioteca de retos", campaign.get("library_version") or "-"),
        ("Ontología", campaign.get("ontology_version") or "-"),
    ]
    artifacts: list[list[Any]] = [[_m("Veredicto", _SMALL), _m("SHA-256 del artefacto", _SMALL)]]
    artifacts += [[_p(a["verdict_id"], _CODE), _p(a["sha256"], _CODE)] for a in chain["artifacts"]]
    return [
        PageBreak(),
        _m("Anexo técnico · cadena de evidencia", _H2),
        _m(
            "Para comprobar el expediente pieza a pieza con el comprobador público o con "
            "<font name='Courier'>tools/verify_evidence.py</font>.",
            _SMALL,
        ),
        Spacer(1, 2 * mm),
        _table([[_p(k, _SMALL), _p(v, _CODE)] for k, v in facts], [50 * mm, 120 * mm], False),
        Spacer(1, 4 * mm),
        _p(f"Artefactos de evidencia ({len(chain['artifacts'])})", _H3),
        _table(artifacts, [62 * mm, 108 * mm]),
    ]


def render_pdf(dossier_json: bytes, verifier_url: str) -> bytes:
    """The PDF of a dossier whose own hash checks out."""
    if not verify_artifact(dossier_json):
        raise DossierError("the dossier does not match its own hash: it is not rendered")
    dossier: dict[str, Any] = json.loads(dossier_json)
    digest = file_digest(dossier_json)
    labels = _Labels(dossier)

    def footer(canvas: Canvas, _: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 10 * mm, f"SHA-256 del expediente: {digest}")
        canvas.drawRightString(190 * mm, 10 * mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        invariant=1,
        title=f"Expediente {dossier['campaign']['id']}",
        author="ARGOS",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    story = [
        *_first_page(dossier, labels, digest, verifier_url),
        *_problems(dossier, labels),
        *_by_obligation(dossier, labels),
        *_texts(dossier),
        *_annex(dossier, digest),
    ]
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
