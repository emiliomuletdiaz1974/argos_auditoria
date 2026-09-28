"""Oracle connector: native catalogue and unified auditing checks (ARG-016)."""

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

from argos_connector.probes import ProbeSpec

from .generic import ConfigCheck, SqlConnector

ORACLE_SYSTEM_SCHEMAS = (
    "SYS",
    "SYSTEM",
    "XDB",
    "OUTLN",
    "MDSYS",
    "CTXSYS",
    "DBSNMP",
    "ORDSYS",
    "WMSYS",
    "LBACSYS",
    "GSMADMIN_INTERNAL",
    "APPQOSSYS",
    "DVSYS",
    "AUDSYS",
    "OJVMSYS",
    "OLAPSYS",
    "DBSFWUSER",
)
# The IN list comes from the fixed tuple above, never from input. Columns of tables only (a view
# is not where the data lives), of users Oracle does not maintain itself (QA-024).
SCHEMA_SQL = (
    "SELECT c.owner, c.table_name, c.column_name, c.data_type, c.nullable "  # noqa: S608
    "FROM all_tab_columns c "
    "JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name "
    "JOIN all_users u ON u.username = c.owner AND u.oracle_maintained = 'N' "
    "WHERE c.owner NOT IN ("
    + ", ".join(f"'{schema}'" for schema in ORACLE_SYSTEM_SCHEMAS)
    + ") ORDER BY c.owner, c.table_name, c.column_id"
)
# An Oracle schema name as the catalogue stores it: checked before it reaches the statement.
_SCHEMA_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}\Z")


def schema_sql(schemas: list[str]) -> str:
    """The scan, narrowed to the schemas a campaign asked for, as the other connectors do."""
    if not schemas:
        return SCHEMA_SQL
    for schema in schemas:
        if not _SCHEMA_NAME.match(schema):
            raise ValueError(f"not an Oracle schema name: {schema!r}")
    wanted = ", ".join(f"'{schema}'" for schema in sorted(set(schemas)))
    return SCHEMA_SQL.replace(" ORDER BY", f" AND c.owner IN ({wanted}) ORDER BY", 1)


class OracleConnector(SqlConnector):
    kind = "rdbms.oracle"
    CONFIG_CHECKS: ClassVar[Mapping[str, ConfigCheck]] = {
        "audit_status": ConfigCheck(
            "SELECT policy_name, enabled_option FROM audit_unified_enabled_policies"
        ),
        "generic_accounts": ConfigCheck(
            "SELECT username, account_status, profile FROM dba_users WHERE oracle_maintained = 'N'"
        ),
        "privileged_grants": ConfigCheck(
            "SELECT grantee, granted_role FROM dba_role_privs WHERE granted_role IN "
            "('DBA', 'IMP_FULL_DATABASE', 'EXP_FULL_DATABASE', 'DATAPUMP_EXP_FULL_DATABASE')"
        ),
    }

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "scan_schema":
            return replace(spec, statement=schema_sql(list(spec.params.get("schemas", []))))
        return super().render(spec)

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        schemas: dict[str, dict[str, Any]] = {}
        columns = 0
        for row in self._rows(spec):
            table = schemas.setdefault(row.owner, {}).setdefault(row.table_name, {"columns": []})
            table["columns"].append(
                {"name": row.column_name, "type": row.data_type, "nullable": row.nullable == "Y"}
            )
            columns += 1
        return {"schemas": schemas}, columns
