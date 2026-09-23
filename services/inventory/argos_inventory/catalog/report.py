"""Readable inventory report: the first deliverable a DPO sees (ARG-026, Plan Director order 10).

Markdown built only from metadata already in the catalog and the graph, so no sampled value can
reach it. Inferred flows and AI candidates are always labelled as such, never presented as facts.
The visible text lives in LABELS: the report is product copy for the customer's DPO.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from argos_inventory.graph.store import GraphStore

from .views import coverage, freshness

LABELS: dict[str, dict[str, str]] = {
    "es": {
        "title": "Informe de inventario",
        "generated": "Generado",
        "summary": "Resumen",
        "systems": "Sistemas",
        "special": "Datos de categorías especiales",
        "flows": "Flujos entre sistemas",
        "ai": "Sistemas de IA candidatos",
        "review": "Cola de revisión",
        "treatments": "Tratamientos declarados",
        "warnings": "Advertencias",
        "empty": "_Sin elementos._",
        "yes": "sí",
        "no": "no",
        "registered": "Sistemas registrados",
        "scanned": "Explorados",
        "without_owner": "Sin responsable",
        "mean_coverage": "Cobertura media (%)",
        "system": "Sistema",
        "kind": "Tipo",
        "owner": "Responsable",
        "last_scan": "Última exploración",
        "status": "Estado",
        "coverage": "Cobertura (%)",
        "missing": "Activos desaparecidos",
        "column": "Columna",
        "category": "Categoría",
        "method": "Método",
        "confidence": "Confianza",
        "source": "Origen",
        "target": "Destino",
        "state": "Situación",
        "inferred": "inferido, pendiente de confirmar",
        "confirmed": "confirmado",
        "external": "externo",
        "candidate": "Candidato",
        "signals": "Señales",
        "pending": "pendiente de confirmación",
        "pending_reviews": "Columnas pendientes",
        "treatment": "Tratamiento",
        "name": "Nombre",
        "legal_basis": "Base jurídica",
        "retention": "Plazo",
        "warn_owner": "Sistemas sin responsable: {names}.",
        "warn_scan": "Sistemas sin exploración: {names}.",
        "warn_flows": "{count} flujo(s) inferido(s) sin confirmar.",
        "warn_reviews": "{count} columna(s) pendientes de revisión.",
        "warn_ai": "{count} sistema(s) de IA pendientes de confirmación.",
        "no_warnings": "Sin advertencias.",
    }
}

_FLOWS = (
    "MATCH (a:System)-[f:FLOWS_TO]->(b:System) "
    "RETURN a.name, b.name, b.key, b.external, f.method, f.confidence, f.confirmed"
)
_FLOW_COLUMNS = ("source", "target", "target_key", "external", "method", "confidence", "confirmed")
_AI = (
    "MATCH (s:System)-[:USES_MODEL]->(a:AISystem) "
    "RETURN s.name, a.name, a.confidence, a.status, a.signals"
)
_TREATMENTS = (
    "MATCH (t:Treatment) OPTIONAL MATCH (s:System)-[:DECLARED_IN]->(t) "
    "RETURN t.id, t.name, t.legal_basis, t.retention, s.name"
)
_SPECIAL = (
    "SELECT system_name, qualified_name, category, method, confidence "
    "FROM argos.catalog_columns WHERE category LIKE 'special_category.%' AND NOT missing "
    "ORDER BY system_name, qualified_name"
)
_PENDING = (
    "SELECT s.name, count(*) AS pending FROM argos.review_queue q JOIN argos.systems s "
    "ON s.id = q.system_id WHERE q.status = 'pending' GROUP BY s.name ORDER BY s.name"
)


def markdown_cell(value: Any, labels: dict[str, str]) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return labels["yes"] if value else labels["no"]
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int | Decimal):  # a count is not text of the client
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return code_span(str(value))


def code_span(text: str) -> str:
    """The client's text as a Markdown code span: never rendered as Markdown nor HTML (SEC-055).

    A name like `<img src=x onerror=…>` is shown, not executed. The fence is one backtick longer
    than the longest run inside, the pipe is escaped for the table and line breaks become spaces.
    """
    flat = text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    longest = max((len(run) for run in re.findall(r"`+", flat)), default=0)
    fence = "`" * (longest + 1)
    padded = f" {flat} " if longest else flat
    return f"{fence}{padded}{fence}"


def markdown_table(
    headers: Sequence[str], rows: Sequence[Sequence[Any]], labels: dict[str, str]
) -> list[str]:
    if not rows:
        return [labels["empty"]]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(markdown_cell(v, labels) for v in row) + " |" for row in rows]
    return lines


def _query(dsn: str, sql: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return list(conn.execute(sql).fetchall())


def render_inventory_report(
    store: GraphStore,
    dsn: str,
    generated_at: datetime | None = None,
    language: str = "es",
) -> str:
    labels = LABELS[language]
    moment = (generated_at or datetime.now(UTC)).astimezone(UTC)
    systems = freshness(dsn)
    coverage_by_system = {str(r["system_id"]): r for r in coverage(dsn)}
    special = _query(dsn, _SPECIAL)
    pending = _query(dsn, _PENDING)
    flows = store.query(_FLOWS, columns=_FLOW_COLUMNS)
    ai = store.query(_AI, columns=("system", "name", "confidence", "status", "signals"))
    treatments: dict[str, dict[str, Any]] = {}
    for row in store.query(_TREATMENTS, columns=("id", "name", "basis", "retention", "system")):
        entry = treatments.setdefault(str(row["id"]), {**row, "systems": []})
        if row["system"]:
            entry["systems"].append(str(row["system"]))

    percentages = [
        float(r["coverage_pct"])
        for r in coverage_by_system.values()
        if r["coverage_pct"] is not None
    ]
    without_owner = sorted(str(r["name"]) for r in systems if not r["has_owner"])
    never_scanned = sorted(str(r["name"]) for r in systems if r["last_scan_at"] is None)
    unconfirmed = [f for f in flows if not f["confirmed"]]
    pending_ai = [a for a in ai if a["status"] != "confirmed"]

    lines = [f"# {labels['title']}", "", f"{labels['generated']}: {moment.isoformat()}", ""]
    lines += [f"## {labels['summary']}", ""]
    lines += markdown_table(
        [labels["registered"], labels["scanned"], labels["without_owner"], labels["mean_coverage"]],
        [
            [
                len(systems),
                sum(1 for r in systems if r["last_scan_at"] is not None),
                len(without_owner),
                round(sum(percentages) / len(percentages), 1) if percentages else None,
            ]
        ],
        labels,
    )
    lines += ["", f"## {labels['systems']}", ""]
    lines += markdown_table(
        [
            labels["system"],
            labels["kind"],
            labels["owner"],
            labels["last_scan"],
            labels["status"],
            labels["coverage"],
            labels["missing"],
        ],
        [
            [
                r["name"],
                r["kind"],
                r["owner"],
                r["last_scan_at"],
                r["last_scan_status"],
                coverage_by_system.get(str(r["system_id"]), {}).get("coverage_pct"),
                r["missing_assets"],
            ]
            for r in systems
        ],
        labels,
    )
    lines += ["", f"## {labels['special']}", ""]
    lines += markdown_table(
        [
            labels["system"],
            labels["column"],
            labels["category"],
            labels["method"],
            labels["confidence"],
        ],
        [
            [r["system_name"], r["qualified_name"], r["category"], r["method"], r["confidence"]]
            for r in special
        ],
        labels,
    )
    lines += ["", f"## {labels['flows']}", ""]
    lines += markdown_table(
        [
            labels["source"],
            labels["target"],
            labels["method"],
            labels["confidence"],
            labels["state"],
        ],
        [
            [
                f["source"],
                f["target"] or f"{labels['external']}: {f['target_key']}",
                f["method"],
                f["confidence"],
                labels["confirmed"] if f["confirmed"] else labels["inferred"],
            ]
            for f in flows
        ],
        labels,
    )
    lines += ["", f"## {labels['ai']}", ""]
    lines += markdown_table(
        [
            labels["system"],
            labels["candidate"],
            labels["confidence"],
            labels["status"],
            labels["signals"],
        ],
        [
            [
                a["system"],
                a["name"],
                a["confidence"],
                labels["confirmed"] if a["status"] == "confirmed" else labels["pending"],
                ", ".join(sorted({str(s).split("|", 1)[0] for s in (a["signals"] or [])})),
            ]
            for a in ai
        ],
        labels,
    )
    lines += ["", f"## {labels['review']}", ""]
    lines += markdown_table(
        [labels["system"], labels["pending_reviews"]],
        [[r["name"], r["pending"]] for r in pending],
        labels,
    )
    lines += ["", f"## {labels['treatments']}", ""]
    lines += markdown_table(
        [
            labels["treatment"],
            labels["name"],
            labels["legal_basis"],
            labels["retention"],
            labels["systems"],
        ],
        [
            [t["id"], t["name"], t["basis"], t["retention"], ", ".join(sorted(t["systems"]))]
            for t in sorted(treatments.values(), key=lambda t: str(t["id"]))
        ],
        labels,
    )
    warnings: list[str] = []
    if without_owner:
        warnings.append(labels["warn_owner"].format(names=", ".join(map(code_span, without_owner))))
    if never_scanned:
        warnings.append(labels["warn_scan"].format(names=", ".join(map(code_span, never_scanned))))
    if unconfirmed:
        warnings.append(labels["warn_flows"].format(count=len(unconfirmed)))
    pending_total = sum(int(r["pending"]) for r in pending)
    if pending_total:
        warnings.append(labels["warn_reviews"].format(count=pending_total))
    if pending_ai:
        warnings.append(labels["warn_ai"].format(count=len(pending_ai)))
    lines += ["", f"## {labels['warnings']}", ""]
    lines += [f"- {w}" for w in warnings] if warnings else [labels["no_warnings"]]
    return "\n".join(lines) + "\n"
