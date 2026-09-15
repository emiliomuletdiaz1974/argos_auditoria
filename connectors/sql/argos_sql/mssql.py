"""SQL Server connector: server audits, SQL logins and privileged role members (ARG-016)."""

from collections.abc import Mapping
from typing import ClassVar

from .generic import ConfigCheck, SqlConnector


class MssqlConnector(SqlConnector):
    kind = "rdbms.mssql"
    CONFIG_CHECKS: ClassVar[Mapping[str, ConfigCheck]] = {
        "audit_status": ConfigCheck("SELECT name, is_state_enabled FROM sys.server_audits"),
        "generic_accounts": ConfigCheck(
            "SELECT name, type_desc, is_disabled FROM sys.sql_logins WHERE name NOT LIKE '##%'"
        ),
        "privileged_grants": ConfigCheck(
            "SELECT p.name AS member_name, r.name AS role_name FROM sys.server_role_members AS m "
            "JOIN sys.server_principals AS p ON p.principal_id = m.member_principal_id "
            "JOIN sys.server_principals AS r ON r.principal_id = m.role_principal_id"
        ),
    }
