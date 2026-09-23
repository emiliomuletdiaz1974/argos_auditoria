"""The four closed tools of the console assistant (ARG-058).

Read-only, with **typed parameters and never a query language**. The model chooses a tool and fills
its arguments; the arguments are validated against the tool's schema before anything runs, and
each tool builds its own parameterised query. There is no tool that takes SQL, Cypher or a filter
written as text, and `test_no_tool_takes_a_query_language` keeps it that way.

- `search_regulation`: the normative corpus (ARG-054).
- `finding_status`: counts of findings by status and severity, with typed filters.
- `inventory_coverage`: the catalogue coverage of one system or all of them (ARG-026).
- `query_graph`: the whitelisted selector of the inventory API (ARG-029), the same one the
  challenge engine uses.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from argos_ai.rag.embeddings import Embedder
from argos_ai.rag.pipeline import retrieve
from argos_inventory.api.selector import ALLOWED_SELECTOR_FIELDS, compile_selector, parse_selector
from argos_inventory.catalog.views import coverage
from argos_inventory.graph.store import GraphStore

UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
FINDING_STATUSES = (
    "open",
    "in_remediation",
    "pending_verification",
    "closed_compliant",
    "reopened",
    "risk_accepted",
)
SEVERITIES = ("critical", "high", "medium", "low")
GRAPH_PAGE = 20
FRAGMENTS = 6
# What a question to the assistant may cost the database: a tool that takes longer is cut by
# PostgreSQL, whatever it asked (security review F09-02, SEC-047).
TOOL_STATEMENT_TIMEOUT = "5s"
# The origins that may be cited as regulation: the client's own documents are not (SEC-048).
REGULATION_ORIGINS = ("norm", "guide")
# Selector fields the graph tool serves: `system_kind` needs the ids of the systems of that kind,
# which the tool does not resolve, so it is not offered (SEC-050).
GRAPH_FIELDS = sorted(ALLOWED_SELECTOR_FIELDS - {"system_kind"})

TOOL_SCHEMAS: Mapping[str, dict[str, Any]] = {
    "search_regulation": {
        "type": "object",
        "required": ["question"],
        "additionalProperties": False,
        "properties": {"question": {"type": "string", "minLength": 3, "maxLength": 300}},
    },
    "finding_status": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"enum": list(FINDING_STATUSES)},
            "severity": {"enum": list(SEVERITIES)},
            "system_id": {"type": "string", "pattern": UUID_PATTERN},
            "challenge_id": {"type": "string", "pattern": "^[a-z]+-[a-z0-9-]+$", "maxLength": 40},
        },
    },
    "inventory_coverage": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"system_id": {"type": "string", "pattern": UUID_PATTERN}},
    },
    "query_graph": {
        "type": "object",
        "required": ["selector"],
        "additionalProperties": False,
        "properties": {
            "selector": {
                "type": "object",
                "propertyNames": {"enum": GRAPH_FIELDS},
            }
        },
    },
}


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    schema: dict[str, Any]
    run: Callable[[dict[str, Any]], dict[str, Any]]


def timeboxed(dsn: str) -> str:
    """The same database, with the statement timeout every tool connection carries."""
    return make_conninfo(dsn, options=f"-c statement_timeout={TOOL_STATEMENT_TIMEOUT}")


def _finding_status(dsn: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    # Fixed conditions, each switched on by its typed argument: nothing the model wrote is
    # formatted into the statement.
    statement = (
        "SELECT status, severity, count(*) FROM argos.findings "
        "WHERE (%(status)s::text IS NULL OR status = %(status)s) "
        "AND (%(severity)s::text IS NULL OR severity = %(severity)s) "
        "AND (%(system_id)s::uuid IS NULL OR system_id = %(system_id)s::uuid) "
        "AND (%(challenge_id)s::text IS NULL OR challenge_id = %(challenge_id)s) "
        "GROUP BY status, severity ORDER BY status, severity"
    )
    params = {
        key: arguments.get(key) for key in ("status", "severity", "system_id", "challenge_id")
    }
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(statement, params).fetchall()
    counts = [{"status": r[0], "severity": r[1], "count": int(r[2])} for r in rows]
    return {"total": sum(row["count"] for row in counts), "by_status_and_severity": counts}


def _inventory_coverage(dsn: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    rows = coverage(dsn, arguments.get("system_id"))
    return {"systems": [{key: str(value) for key, value in row.items()} for row in rows]}


def _query_graph(dsn: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    selector = parse_selector(dict(arguments["selector"]))
    cypher, params = compile_selector(selector, first=GRAPH_PAGE)
    rows = GraphStore(dsn).query(
        cypher, params, ("key", "label", "name", "qualified_name", "system_id")
    )
    # The selector asks for one row more than a page to know whether there are more.
    nodes = [
        {"name": str(row["name"]), "qualified_name": str(row["qualified_name"])}
        for row in rows[:GRAPH_PAGE]
    ]
    return {"count": len(nodes), "truncated": len(rows) > GRAPH_PAGE, "nodes": nodes}


def _search_regulation(
    dsn: str, embedder: Embedder, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    hits = retrieve(dsn, str(arguments["question"]), embedder, REGULATION_ORIGINS)[:FRAGMENTS]
    return {"fragments": [{"reference": hit.reference, "text": hit.text[:400]} for hit in hits]}


def default_toolbox(dsn: str, embedder: Embedder) -> dict[str, Tool]:
    """The four tools bound to the appliance database. There is no fifth.

    Every connection they open carries the statement timeout (SEC-047).
    """
    dsn = timeboxed(dsn)
    runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "search_regulation": lambda arguments: _search_regulation(dsn, embedder, arguments),
        "finding_status": lambda arguments: _finding_status(dsn, arguments),
        "inventory_coverage": lambda arguments: _inventory_coverage(dsn, arguments),
        "query_graph": lambda arguments: _query_graph(dsn, arguments),
    }
    return {name: Tool(name, TOOL_SCHEMAS[name], runners[name]) for name in TOOL_SCHEMAS}
