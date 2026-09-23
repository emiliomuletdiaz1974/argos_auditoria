"""What a configuration check may read, and what of it may leave the connector in clear (SEC-022).

`check_config` exists to read how a system is configured: its settings, its roles, its grants. A
challenge that declares its own statement could point it at a business table instead and bring the
table into the evidence. So:

- the statement may only read **catalogue and configuration** sources of its dialect (system
  views, `information_schema`, settings); a table of the client is refused before journaling, and
  the challenge lint refuses it before the library is published;
- only the columns that name a setting or an identity of the system travel in clear; any other
  column is a keyed digest, like a sample;
- a check brings at most `max_rows_per_probe` rows.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from argos_connector.minimize import ValueHasher

# The catalogue and configuration sources of each dialect, by schema and by name prefix.
_SCHEMAS: Mapping[str, frozenset[str]] = {
    "postgres": frozenset({"pg_catalog", "information_schema"}),
    "mysql": frozenset({"information_schema", "performance_schema", "mysql", "sys"}),
    "tsql": frozenset({"sys", "information_schema"}),
    "oracle": frozenset({"sys"}),
    "sqlite": frozenset(),
}
_PREFIXES: Mapping[str, tuple[str, ...]] = {
    "postgres": ("pg_",),
    "mysql": (),
    "tsql": (),
    "oracle": ("dba_", "all_", "user_", "v$", "gv$", "audit_unified_"),
    "sqlite": ("sqlite_", "pragma_"),
}
# Columns that name a setting or an identity of the system itself: they travel in clear. Anything
# else a check returns is a digest.
CLEAR_COLUMNS = frozenset(
    {
        "account_status",
        "enabled_option",
        "granted_role",
        "grantee",
        "is_disabled",
        "is_state_enabled",
        "lag_s",
        "member_name",
        "name",
        "policy_name",
        "privilege_type",
        "profile",
        "role_name",
        "setting",
        "standby",
        "type_desc",
        "username",
        "value",
        "variable_name",
        "variable_value",
    }
)


def _allowed(table: exp.Table, dialect: str) -> bool:
    name = table.name.lower()
    schema = (table.db or "").lower()
    if schema:
        return schema in _SCHEMAS.get(dialect, frozenset()) or name.startswith(
            _PREFIXES.get(dialect, ())
        )
    return name.startswith(_PREFIXES.get(dialect, ())) or name in _SCHEMAS.get(dialect, ())


def check_config_sources(statement: str, dialect: str) -> None:
    """Nothing if every source of the statement is catalogue or configuration; else ValueError."""
    try:
        trees = [tree for tree in sqlglot.parse(statement, read=dialect) if tree is not None]
    except ParseError as exc:
        raise ValueError(f"a configuration check that does not parse: {exc}") from exc
    ctes = {cte.alias_or_name.lower() for tree in trees for cte in tree.find_all(exp.CTE)}
    offending: list[str] = []
    for tree in trees:
        for table in tree.find_all(exp.Table):
            if not table.name or table.name.lower() in ctes:
                continue  # a table function (aclexplode(…)) or a CTE of the statement itself
            if isinstance(table.this, exp.Func):
                continue
            if not _allowed(table, dialect):
                offending.append(".".join(part for part in (table.db, table.name) if part))
    if offending:
        raise ValueError(
            f"a configuration check reads only catalogue and configuration sources, "
            f"not {sorted(set(offending))}"
        )


def minimise_config_rows(
    rows: Iterable[Mapping[str, Any]],
    hasher: ValueHasher,
    max_rows: int,
    jsonable: Callable[[Any], Any] = lambda value: value,
) -> list[dict[str, Any]]:
    """At most `max_rows` rows; a column that is not a setting travels as a digest."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        if len(kept) >= max_rows:
            break
        kept.append(
            {
                key: jsonable(value) if key.lower() in CLEAR_COLUMNS else hasher.digest(value)
                for key, value in row.items()
            }
        )
    return kept
