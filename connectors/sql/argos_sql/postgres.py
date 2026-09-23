"""PostgreSQL connector: deep catalogue and access checks, no business rows read (ARG-015)."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

from argos_connector.probes import ProbeSpec

from .generic import ConfigCheck, SqlConnector

# One row per column (one with NULL column for a table without columns), with the size of its
# table: the whole scan is this single journaled statement (SEC-023).
CATALOG_SQL = (
    "SELECT n.nspname AS schema_name, c.relname AS table_name, a.attname AS column_name, "
    "pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type, "
    "NOT a.attnotnull AS nullable, "
    "pg_total_relation_size(c.oid) AS bytes, CAST(c.reltuples AS bigint) AS est_rows, "
    "obj_description(c.oid, 'pg_class') AS comment, pg_is_in_recovery() AS standby "
    "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
    "LEFT JOIN pg_attribute AS a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
    "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%' "
    "ORDER BY n.nspname, c.relname, a.attnum"
)
PRIVILEGES_SQL = (
    "SELECT grantee.rolname AS role_name, acl.privilege_type AS privilege_type "
    "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
    "JOIN LATERAL aclexplode(c.relacl) AS acl ON true "
    "JOIN pg_roles AS grantee ON grantee.oid = acl.grantee "
    "WHERE n.nspname = :schema AND c.relname = :table "
    "UNION "
    # By oid, never by the name as text: `Pacientes.2024` would need quoting (SEC-054).
    "SELECT r.rolname AS role_name, 'SELECT (effective)' AS privilege_type "
    "FROM pg_roles AS r, pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
    "WHERE n.nspname = :schema AND c.relname = :table "
    "AND r.rolcanlogin AND has_table_privilege(r.rolname, c.oid, 'SELECT')"
)
ENCRYPTION_SQL = (
    "SELECT name, setting FROM pg_settings "
    "WHERE name IN ('ssl', 'password_encryption', 'data_checksums')"
)
REPLICA_SQL = (
    "SELECT pg_is_in_recovery() AS standby, "
    "EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp()) AS lag_s"
)


class PostgresConnector(SqlConnector):
    kind = "rdbms.postgresql"
    CONFIG_CHECKS: ClassVar[Mapping[str, ConfigCheck]] = {
        "privileges": ConfigCheck(PRIVILEGES_SQL, ("schema", "table")),
        "encryption_at_rest": ConfigCheck(ENCRYPTION_SQL),
        "replica_status": ConfigCheck(REPLICA_SQL),
    }

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "scan_schema":
            return replace(spec, statement=CATALOG_SQL)
        return super().render(spec)

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        wanted = set(spec.params.get("schemas", []))
        schemas: dict[str, dict[str, Any]] = {}
        columns, standby = 0, False
        for row in self._rows(spec):
            standby = bool(row.standby)
            if wanted and row.schema_name not in wanted:
                continue
            table = schemas.setdefault(row.schema_name, {}).setdefault(
                row.table_name,
                {
                    "columns": [],
                    "bytes": int(row.bytes),
                    "est_rows": int(row.est_rows),
                    "comment": row.comment,
                },
            )
            if row.column_name is not None:
                table["columns"].append(
                    {
                        "name": row.column_name,
                        "type": str(row.data_type).upper(),
                        "nullable": bool(row.nullable),
                    }
                )
                columns += 1
        # passive mode: the connection points at a standby
        return {"schemas": schemas, "is_replica": standby}, columns

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        data, rows = super()._do_check_config(spec)
        if spec.params.get("check") == "encryption_at_rest":
            data["note"] = "encryption at rest is evidenced at volume level"
        return data, rows
