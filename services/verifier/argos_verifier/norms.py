"""The norms namespace, dereferenced: `https://ns.argos.eu/norms/{name}` answers what it names.

Findings and the signed evidence point to obligations by their IRI. Whoever serves the namespace
(`ns.argos.eu`, or the bench name until that domain is ours) routes `/norms/` here, and the IRI
opens: a page of the catalogue for a person, Turtle or JSON-LD for a program. The catalogue is
the published population this image carries (the core, the norms, the generated obligations and
the asset classes), read once; it also downloads whole, as Markdown and as PDF. The pages link to
the other nodes by path, so they stay on the host that served them, and run no script.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.term import Node
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NORMS = Namespace("https://ns.argos.eu/norms/")
ARGOS = Namespace("https://ns.argos.eu/core#")
ONTOLOGY_DIR = Path(
    os.environ.get(
        "ARGOS_ONTOLOGY_DIR",
        str(Path(__file__).resolve().parents[3] / "library" / "ontology"),
    )
)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SOURCES = ("core/*.ttl", "norms/*.ttl", "norms/generated/*.ttl", "asset-classes/*.ttl")
TITLE = "Catálogo normativo de ARGOS"
NOTICE = (
    "Contenido pendiente de validación jurídica: las obligaciones las estructura el equipo de "
    "ARGOS a partir de cada norma y todavía no las ha revisado un perfil jurídico. No sustituyen "
    "al texto oficial, que se enlaza en cada norma."
)
ABSTRACT = (
    "Cada obligación de este catálogo es una exigencia de una norma escrita de forma que se pueda "
    "comprobar en los sistemas de una organización: de qué artículo deriva, a qué datos aplica, "
    "desde cuándo está en vigor, su severidad y qué retos de ARGOS la verifican. Los hallazgos y "
    "la evidencia firmada de ARGOS citan cada obligación por su IRI, que es la dirección de su "
    "página en este catálogo."
)
SEVERITY = {"critical": "Crítica", "high": "Alta", "medium": "Media", "low": "Baja"}
# Shown first and in this order; any other property of the node follows, by its label.
ORDER = (
    ARGOS.derivesFrom,
    ARGOS.partOf,
    ARGOS.severity,
    ARGOS.inForceFrom,
    ARGOS.eli,
    ARGOS.verifiedBy,
    ARGOS.appliesTo,
)
STYLE = """
:root{--bg:#f7f8fa;--panel:#fff;--text:#1d2433;--muted:#5b6475;--line:#e3e6ec;--accent:#1d4ed8;
--accent-soft:#e8efff;--warn-bg:#fff7e6;--warn-line:#f0b429;--warn-text:#7a4a00}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--panel:#1a1f29;--text:#e6e9ef;
--muted:#9aa3b2;--line:#2b3240;--accent:#8ab4ff;--accent-soft:#1f2a44;--warn-bg:#2b2412;
--warn-line:#b7871f;--warn-text:#f3d08a}}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text);
background:var(--bg)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;gap:.5rem 1rem;
align-items:center;justify-content:space-between;padding:.7rem 1rem;background:var(--panel);
border-bottom:1px solid var(--line)}
.brand{font-weight:700;letter-spacing:.02em;color:var(--text)}
.brand small{font-weight:500;color:var(--muted);margin-left:.4rem}
.downloads{display:flex;gap:.5rem}
.button{display:inline-block;padding:.35rem .8rem;border-radius:.45rem;font-size:.9rem;
font-weight:600;border:1px solid var(--accent)}
.button.primary{background:var(--accent);color:var(--panel)}
.layout{display:grid;grid-template-columns:18rem minmax(0,1fr);max-width:78rem;margin:0 auto}
nav{position:sticky;top:3.4rem;align-self:start;max-height:calc(100vh - 3.4rem);overflow:auto;
padding:1.2rem 1rem;border-right:1px solid var(--line);font-size:.88rem}
nav h2{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
margin:0 0 .6rem}
nav ul{list-style:none;margin:0;padding:0}nav li{margin:.1rem 0}
nav .norm{margin-top:.8rem;font-weight:600}
nav a{display:block;padding:.15rem .5rem;border-radius:.35rem;color:var(--text)}
nav .obligations a{color:var(--muted);padding-left:1rem;font-weight:400}
nav a[aria-current=page]{background:var(--accent-soft);color:var(--accent)}
main{padding:1.6rem 2rem 4rem;min-width:0}
.kind{color:var(--muted);text-transform:uppercase;font-size:.75rem;letter-spacing:.08em;margin:0}
h1{font-size:1.8rem;line-height:1.25;margin:.2rem 0 1rem}
h2{font-size:1.2rem;margin:2rem 0 .6rem}
.notice{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-text);
border-radius:.5rem;padding:.7rem .9rem;font-size:.9rem;margin:0 0 1.4rem}
.lead{font-size:1.05rem}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
font-size:.92rem}
th,td{text-align:left;padding:.55rem .75rem;border-bottom:1px solid var(--line);
vertical-align:top}
th{font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
tbody th{width:12rem}
td ul{margin:0;padding-left:1.1rem}
code{font-size:.85em;word-break:break-all}
td a{overflow-wrap:anywhere}
@media (max-width:760px){.layout{display:block}nav{position:static;max-height:16rem;
border-right:0;border-bottom:1px solid var(--line)}main{padding:1.2rem 1rem 3rem}
h1{font-size:1.45rem}tbody th{width:auto}}
"""


@dataclass(frozen=True)
class Obligation:
    id: str
    title: str
    summary: str
    article: str
    severity: str
    in_force_from: str
    verified_by: tuple[str, ...]
    applies_to: tuple[str, ...]
    pending: str


@dataclass(frozen=True)
class Norm:
    id: str
    title: str
    eli: str
    in_force_from: str
    obligations: tuple[Obligation, ...]


@lru_cache(maxsize=1)
def population() -> Graph:
    graph = Graph()
    for pattern in SOURCES:
        for path in sorted(ONTOLOGY_DIR.glob(pattern)):
            graph.parse(path, format="turtle")
    return graph


def node(name: str) -> URIRef | None:
    """The IRI of `name` if the namespace has it; the name never reaches a file path."""
    if not NAME.match(name):
        return None
    iri = NORMS[name]
    return iri if (iri, None, None) in population() else None


def description(graph: Graph, iri: URIRef) -> Graph:
    """The triples of the node, with the prefixes of the population."""
    found = Graph()
    for prefix, namespace in (("n", NORMS), ("argos", ARGOS), ("rdfs", RDFS)):
        found.bind(prefix, namespace)
    for triple in graph.triples((iri, None, None)):
        found.add(triple)
    return found


def _name(term: Node) -> str:
    return str(term).removeprefix(str(NORMS))


def _text(graph: Graph, term: Node, prop: URIRef) -> str:
    value = graph.value(term, prop)
    return "" if value is None else str(value)


def _label(graph: Graph, term: Node) -> str:
    label = _text(graph, term, RDFS.label)
    if label:
        return label
    if isinstance(term, URIRef) and str(term).startswith(str(NORMS)):
        return _name(term)
    return str(term)


def version(graph: Graph) -> str:
    return _text(graph, URIRef(str(ARGOS)), OWL.versionInfo) or "sin versión"


def _natural(obligation: Obligation) -> list[object]:
    """OBL-RGPD-5-1 before OBL-RGPD-15-1."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", obligation.id)]


def _obligation(graph: Graph, obligation: Node, article: Node) -> Obligation:
    challenges = graph.objects(obligation, ARGOS.verifiedBy)
    return Obligation(
        id=_name(obligation),
        title=_label(graph, obligation),
        summary=_text(graph, obligation, RDFS.comment),
        article=_label(graph, article),
        severity=_text(graph, obligation, ARGOS.severity),
        in_force_from=_text(graph, obligation, ARGOS.inForceFrom),
        verified_by=tuple(
            sorted(_text(graph, c, ARGOS.challengeId) or _name(c) for c in challenges)
        ),
        applies_to=tuple(
            sorted(_label(graph, a) for a in graph.objects(obligation, ARGOS.appliesTo))
        ),
        pending=_text(graph, obligation, ARGOS.verificationPending),
    )


@lru_cache(maxsize=1)
def catalogue() -> tuple[Norm, ...]:
    """Every norm with its obligations, as the population says, in a stable order."""
    graph = population()
    norms = []
    for norm in sorted(graph.subjects(RDF.type, ARGOS.Norm), key=str):
        obligations = [
            _obligation(graph, obligation, article)
            for article in graph.subjects(ARGOS.partOf, norm)
            for obligation in graph.subjects(ARGOS.derivesFrom, article)
        ]
        norms.append(
            Norm(
                id=_name(norm),
                title=_label(graph, norm),
                eli=_text(graph, norm, ARGOS.eli),
                in_force_from=_text(graph, norm, ARGOS.inForceFrom),
                obligations=tuple(sorted(obligations, key=_natural)),
            )
        )
    return tuple(norms)


# ---------- HTML ----------


def _link(name: str, text: str, current: str | None = None) -> str:
    marked = ' aria-current="page"' if name == current else ""
    return f'<a{marked} href="/norms/{escape(name)}">{escape(text)}</a>'


def _external(url: str) -> str:
    return f'<a href="{escape(url)}" rel="noopener">{escape(url)}</a>'


def _value(graph: Graph, term: Node) -> str:
    if isinstance(term, Literal) and term.datatype != XSD.anyURI:
        text = str(term)
        return escape(SEVERITY.get(text, text))
    text = str(term)
    if text.startswith(str(NORMS)):
        challenge = _text(graph, term, ARGOS.challengeId)
        return _link(_name(term), challenge or _label(graph, term))
    if text.startswith(("https://", "http://")):
        return _external(text)
    return escape(text)


def _cell(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return "<ul>" + "".join(f"<li>{v}</li>" for v in values) + "</ul>"


def _row(graph: Graph, prop: Node, values: list[Node]) -> str:
    shown = sorted(_value(graph, v) for v in values)
    if not shown:
        return ""
    return f"<tr><th scope=row>{escape(_label(graph, prop))}</th><td>{_cell(shown)}</td></tr>"


def _shell(title: str, current: str | None, content: str) -> str:
    index = []
    for norm in catalogue():
        items = "".join(f"<li>{_link(o.id, o.id, current)}</li>" for o in norm.obligations)
        index.append(
            f'<li class="norm">{_link(norm.id, norm.id, current)}'
            f'<ul class="obligations">{items}</ul></li>'
        )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        f'<header><a class="brand" href="/norms/">{escape(TITLE)}'
        f"<small>v{escape(version(population()))}</small></a>"
        '<span class="downloads"><a class="button primary" href="/norms/catalogo.pdf">'
        'Descargar PDF</a><a class="button" href="/norms/catalogo.md">Descargar MD</a></span>'
        '</header><div class="layout"><nav aria-label="Índice"><h2>Índice de contenidos</h2>'
        f"<ul><li>{_link('', 'Presentación', current)}</li>{''.join(index)}</ul></nav>"
        f'<main><p class="notice" role="note">{escape(NOTICE)}</p>{content}</main></div>'
        "</body></html>"
    )


def front_page() -> str:
    rows = "".join(
        f"<tr><td>{_link(n.id, n.title)}</td><td>{len(n.obligations)}</td>"
        f"<td>{escape(n.in_force_from)}</td>"
        f"<td>{_external(n.eli) if n.eli else '—'}</td></tr>"
        for n in catalogue()
    )
    content = (
        f'<p class="kind">Espacio de nombres {escape(str(NORMS))}</p><h1>{escape(TITLE)}</h1>'
        f'<p class="lead">{escape(ABSTRACT)}</p><h2>Normas</h2><table><thead><tr><th>Norma</th>'
        "<th>Obligaciones</th><th>En vigor desde</th><th>Texto oficial</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _shell(TITLE, "", content)


def page(graph: Graph, iri: URIRef) -> str:
    """The node in the catalogue: its label, its comment, its properties and where it comes from."""
    title = _label(graph, iri)
    kinds = [_label(graph, k) for k in graph.objects(iri, RDF.type)]
    comment = graph.value(iri, RDFS.comment)
    props: list[Node] = [p for p in ORDER if (iri, p, None) in graph]
    shown_apart = {*ORDER, RDF.type, RDFS.label, RDFS.comment}
    props += sorted({p for p in graph.predicates(iri, None)} - shown_apart, key=str)
    rows = [_row(graph, p, list(graph.objects(iri, p))) for p in props]
    # An obligation names its article; the article names its norm. The norm and its official text
    # are what a reader looks for next, so they are shown here too.
    for article in graph.objects(iri, ARGOS.derivesFrom):
        for norm in graph.objects(article, ARGOS.partOf):
            rows.append(_row(graph, ARGOS.partOf, [norm]))
            rows.append(_row(graph, ARGOS.eli, list(graph.objects(norm, ARGOS.eli))))
    # A norm lists its obligations, which only point to it through their articles.
    for listed in catalogue():
        if listed.id == _name(iri) and listed.obligations:
            items = [_link(o.id, f"{o.id} · {o.title}") for o in listed.obligations]
            rows.append(f"<tr><th scope=row>Obligaciones</th><td>{_cell(items)}</td></tr>")
    content = (
        f'<p class="kind">{escape(", ".join(kinds))}</p><h1>{escape(title)}</h1>'
        + (f'<p class="lead">{escape(str(comment))}</p>' if comment is not None else "")
        + f"<table><tbody>{''.join(rows)}<tr><th scope=row>IRI</th>"
        f"<td><code>{escape(str(iri))}</code></td></tr></tbody></table>"
    )
    return _shell(f"{title} · {TITLE}", _name(iri), content)


# ---------- downloads ----------


def _facts(o: Obligation) -> list[tuple[str, str]]:
    rows = [
        ("Artículo", o.article),
        ("Severidad", SEVERITY.get(o.severity, o.severity)),
        ("En vigor desde", o.in_force_from),
        ("Verificada por", ", ".join(o.verified_by) or "—"),
        ("Aplica a", ", ".join(o.applies_to) or "—"),
    ]
    if o.pending:
        rows.append(("Verificación pendiente", o.pending))
    rows.append(("IRI", f"{NORMS}{o.id}"))
    return rows


def markdown() -> str:
    lines = [
        f"# {TITLE}",
        "",
        f"Versión de la ontología: {version(population())} · Espacio de nombres: {NORMS}",
        "",
        f"> {NOTICE}",
        "",
        ABSTRACT,
        "",
    ]
    for norm in catalogue():
        lines += [
            f"## {norm.title}",
            "",
            f"- Identificador: `{norm.id}` ({NORMS}{norm.id})",
            f"- En vigor desde: {norm.in_force_from}",
        ]
        if norm.eli:
            lines.append(f"- Texto oficial: {norm.eli}")
        lines += [f"- Obligaciones: {len(norm.obligations)}", ""]
        for o in norm.obligations:
            lines += [f"### {o.id} · {o.title}", ""]
            if o.summary:
                lines += [o.summary, ""]
            lines += ["| Campo | Valor |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in _facts(o)]
            lines.append("")
    return "\n".join(lines)


def pdf() -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11)
    notice = ParagraphStyle(
        "notice",
        parent=small,
        backColor=colors.HexColor("#fff7e6"),
        borderColor=colors.HexColor("#f0b429"),
        borderWidth=0.6,
        borderPadding=5,
        spaceBefore=4,
        spaceAfter=10,
    )

    def text(value: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(value), style)

    story: list[object] = [
        Paragraph(escape(TITLE), styles["Title"]),
        text(f"Versión de la ontología {version(population())} · {NORMS}", small),
        Spacer(1, 6),
        text(NOTICE, notice),
        text(ABSTRACT),
    ]
    for norm in catalogue():
        facts = f"{norm.id} · en vigor desde {norm.in_force_from}"
        story += [
            Paragraph(escape(norm.title), styles["Heading1"]),
            text(facts + (f" · texto oficial: {norm.eli}" if norm.eli else ""), small),
        ]
        for o in norm.obligations:
            story.append(Paragraph(escape(f"{o.id} · {o.title}"), styles["Heading3"]))
            if o.summary:
                story.append(text(o.summary))
            table = Table(
                [[text(k, small), text(v, small)] for k, v in _facts(o)],
                colWidths=(38 * mm, 132 * mm),
            )
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5d9e0")),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f4f7")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story += [Spacer(1, 3), table, Spacer(1, 6)]
    out = io.BytesIO()
    SimpleDocTemplate(
        out, pagesize=A4, title=TITLE, author="ARGOS", leftMargin=20 * mm, rightMargin=20 * mm
    ).build(story)
    return out.getvalue()
