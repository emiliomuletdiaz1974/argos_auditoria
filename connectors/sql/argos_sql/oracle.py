"""Oracle connector: native catalogue and unified auditing checks (ARG-016)."""

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
# The IN list comes from the fixed tuple above, never from input.
SCHEMA_SQL = (
    "SELECT owner, table_name, column_name, data_type, nullable FROM all_tab_columns "  # noqa: S608
    "WHERE owner NOT IN ("
    + ", ".join(f"'{schema}'" for schema in ORACLE_SYSTEM_SCHEMAS)
    + ") ORDER BY owner, table_name, column_id"
)


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
            return replace(spec, statement=SCHEMA_SQL)
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
