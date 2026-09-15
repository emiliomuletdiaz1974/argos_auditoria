"""Parameters of the ingest statements: natural keys, qualified names, provenance (ARG-022)."""

from typing import Any, Protocol

from argos_inventory.graph.model import (
    column_key,
    file_area_key,
    identity_key,
    schema_key,
    system_key,
    table_key,
)

PROVENANCE_KEYS = frozenset(
    {"system_id", "run_id", "source_connector", "probe_id", "journal_seq", "observed_at"}
)


class CatalogEntry(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def owner(self) -> str | None: ...


def system_parameters(meta: CatalogEntry, at: str) -> dict[str, Any]:
    return {
        "system_key": system_key(meta.id),
        "system_id": meta.id,
        "name": meta.name,
        "kind": meta.kind,
        "owner": meta.owner,
        "at": at,
    }


def _provenance(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_id": data["system_id"],
        "at": data["observed_at"],
        "source_connector": data["source_connector"],
        "probe_id": data["probe_id"],
        "journal_seq": data["journal_seq"],
    }


def table_parameters(data: dict[str, Any]) -> dict[str, Any]:
    sid, schema, table = str(data["system_id"]), str(data["schema"]), str(data["table"])
    qualified = f"{schema}.{table}"
    columns = [
        {
            "key": column_key(sid, schema, table, str(c["name"])),
            "name": str(c["name"]),
            "qualified_name": f"{qualified}.{c['name']}",
            "type": str(c["type"]),
            "nullable": bool(c["nullable"]),
        }
        for c in data["columns"]
    ]
    return {
        **_provenance(data),
        "system_key": system_key(sid),
        "schema": schema,
        "schema_key": schema_key(sid, schema),
        "table": table,
        "table_key": table_key(sid, schema, table),
        "qualified_name": qualified,
        "est_rows": int(data["est_rows"]),
        "bytes": int(data["bytes"]),
        "comment": data.get("comment"),
        "columns": columns,
    }


def access_parameters(data: dict[str, Any]) -> dict[str, Any]:
    sid = str(data["system_id"])
    by_grantee: dict[str, set[str]] = {}
    for grant in data["grants"]:
        by_grantee.setdefault(str(grant["grantee"]), set()).add(str(grant["privilege"]))
    grants = [
        {"key": identity_key(sid, grantee), "grantee": grantee, "privileges": sorted(privileges)}
        for grantee, privileges in sorted(by_grantee.items())
    ]
    return {
        **_provenance(data),
        "table_key": table_key(sid, str(data["schema"]), str(data["table"])),
        "grants": grants,
    }


def file_area_parameters(data: dict[str, Any]) -> dict[str, Any]:
    sid, path = str(data["system_id"]), str(data["path"])
    return {
        **_provenance(data),
        "system_key": system_key(sid),
        "area_key": file_area_key(sid, path),
        "path": path,
        "name": path or "/",
        "total": int(data["total"]),
        "bytes": int(data["bytes"]),
        "by_ext": dict(data["by_ext"]),
        "age_years": dict(data["age_years"]),
        "capped": bool(data["capped"]),
    }


def summary_parameters(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    summary = {k: v for k, v in data.items() if k not in PROVENANCE_KEYS}
    routes = [str(r["path"]) for r in summary.get("routes", [])]
    return {
        "system_key": system_key(str(data["system_id"])),
        "summary_kind": event_type.split(".")[1],
        "summary": summary,
        "routes": routes,
        "probe_id": data["probe_id"],
    }
