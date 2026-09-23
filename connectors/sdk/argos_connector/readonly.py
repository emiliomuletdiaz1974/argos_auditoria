"""Syntactic read-only guard for declared statements (ARG-011, second line of defence).

The customer's read-only account (first line) and the read-only session opened by each
connector (third line) remain mandatory: this guard never replaces them.

What the guard reads has to be what the engine runs. So it refuses the comments an engine
executes (MySQL `/*! */`, MariaDB `/*M! */`, optimiser hints `/*+ */`, and `--` without a space,
which MySQL does not take as a comment), table and query hints, and any function it does not know:
a function it cannot name could be a user function that writes (in Oracle, an autonomous
transaction commits inside a read-only one). Known functions pass unless they are denied, and the
denied list is checked against every segment of a qualified name (security review F09-02).
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from argos_common.errors import ReadOnlyViolationError

SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = tuple(
    node
    for node in (
        exp.Select,
        exp.Union,
        exp.Intersect,
        exp.Except,
        getattr(exp, "Describe", None),
        getattr(exp, "Show", None),
    )
    if node is not None
)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "AlterTable",
        "Command",
        "TruncateTable",
        "Into",
        "Copy",
        "Lock",
        "Transaction",
        "Commit",
        "Rollback",
        "Set",
        "Use",
        "Grant",
        "Revoke",
        "Pragma",
        "LoadData",
        "Kill",
        "Analyze",
    )
    if hasattr(exp, name)
)
DENIED_FUNCTIONS = frozenset(
    {
        "pg_sleep_for",
        "pg_sleep_until",
        "nextval",
        "setval",
        "set_config",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_sleep",
        "lo_import",
        "lo_export",
        "lo_unlink",
        "dblink_exec",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "xp_cmdshell",
        "sleep",
        "benchmark",
        "get_lock",
        "load_file",
        "release_lock",
        "query_to_xml",
        "query_to_xml_and_xmlschema",
        "query_to_xmlschema",
        "cursor_to_xml",
        "pg_stat_file",
        "pg_notify",
        "pg_promote",
        "pg_rotate_logfile",
        "pg_switch_wal",
        "pg_logical_emit_message",
    }
)
# Families whose members run arbitrary statements, reach other servers, take locks or touch
# the server's file system. Checked against every segment of a package-qualified name.
DENIED_PREFIXES = (
    "dbms_",
    "utl_",
    "dblink",
    "lo_",
    "xp_",
    "sp_",
    "open",
    "pg_advisory",
    "pg_try_advisory",
    "pg_read",
    "pg_ls_",
    "pg_file",
    "pg_create_",
    "pg_drop_",
    "pg_replication_",
)
# Functions sqlglot does not model (it parses them as anonymous) that catalog and configuration
# probes need, all of them reads. Anything else anonymous is a user function and is refused.
ALLOWED_ANONYMOUS = frozenset(
    {
        # PostgreSQL catalog and statistics
        "aclexplode",
        "acldefault",
        "pg_get_viewdef",
        "quote_ident",
        "has_table_privilege",
        "has_schema_privilege",
        "has_column_privilege",
        "has_database_privilege",
        "format_type",
        "pg_get_expr",
        "pg_get_constraintdef",
        "pg_get_indexdef",
        "pg_get_userbyid",
        "pg_table_is_visible",
        "pg_total_relation_size",
        "pg_relation_size",
        "pg_table_size",
        "pg_indexes_size",
        "pg_database_size",
        "pg_size_pretty",
        "pg_is_in_recovery",
        "pg_last_xact_replay_timestamp",
        "pg_postmaster_start_time",
        "pg_encoding_to_char",
        "obj_description",
        "col_description",
        "current_database",
        "current_schema",
        "current_setting",
        "version",
        "inet_server_addr",
        "to_regclass",
        # SQL Server
        "serverproperty",
        "databasepropertyex",
        "db_name",
        "schema_name",
        "object_name",
        "object_id",
        "has_perms_by_name",
        "is_member",
        "is_srvrolemember",
        "columnproperty",
        "objectproperty",
        # Oracle
        "sys_context",
        # MySQL / MariaDB
        "database",
        "schema",
    }
)
# Schemas whose qualified functions are the engine's own catalog, never a customer package.
CATALOG_SCHEMAS = frozenset({"pg_catalog", "information_schema", "sys", "dbo.sys"})
# Comments an engine executes, and "--" not followed by a space (not a comment in MySQL).
_EXECUTABLE_COMMENT = re.compile(r"/\*\s*(?:!|M!|\+)|--(?![\s]|$)")
_HINTS: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in ("WithTableHint", "IndexTableHint", "QueryOption", "JoinHint")
    if hasattr(exp, name)
)
# A string argument that is itself a write statement, as passed to dblink, OPENQUERY and the like.
_EMBEDDED_WRITE = re.compile(
    r"^\s*(insert|update|delete|merge|create|drop|alter|truncate|grant|revoke|copy|call"
    r"|exec|execute|begin|declare)\b",
    re.IGNORECASE,
)


def _function_name(node: exp.Func) -> str:
    name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
    parent = node.parent
    if isinstance(parent, exp.Dot) and parent.expression is node:
        return f"{parent.this.sql().lower()}.{name}"
    return name


def _is_anonymous(node: exp.Func) -> bool:
    """A function sqlglot does not model: its own or a user's, and the guard cannot tell which."""
    if isinstance(node, exp.Anonymous):
        return True
    parent = node.parent
    return isinstance(parent, exp.Dot) and parent.expression is node


def _is_denied(name: str) -> bool:
    return any(
        segment in DENIED_FUNCTIONS or segment.startswith(DENIED_PREFIXES)
        for segment in name.split(".")
    )


def _is_allowed_anonymous(name: str) -> bool:
    *qualifier, function = name.split(".")
    if qualifier and ".".join(qualifier) not in CATALOG_SCHEMAS:
        return False
    return function in ALLOWED_ANONYMOUS


def validate_read_only_sql(statement: str, dialect: str) -> None:
    if not statement.strip():
        raise ReadOnlyViolationError("empty statement")
    if _EXECUTABLE_COMMENT.search(statement):
        raise ReadOnlyViolationError("comment an engine would execute (/*! */, /*+ */ or --x)")
    try:
        trees = [tree for tree in sqlglot.parse(statement, read=dialect) if tree is not None]
    except ParseError:
        raise ReadOnlyViolationError("statement is not parseable as read-only SQL") from None
    if len(trees) != 1:
        raise ReadOnlyViolationError(f"exactly one statement is allowed, got {len(trees)}")
    root = trees[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise ReadOnlyViolationError(f"statement type not allowed: {type(root).__name__}")
    for item in root.walk():
        node = item[0] if isinstance(item, tuple) else item
        if isinstance(node, _FORBIDDEN_NODES):
            raise ReadOnlyViolationError(f"forbidden construct: {type(node).__name__}")
        if isinstance(node, _HINTS):
            raise ReadOnlyViolationError(f"table or query hint: {type(node).__name__}")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if _is_denied(name):
                raise ReadOnlyViolationError(f"function with side effects: {name}")
            if _is_anonymous(node) and not _is_allowed_anonymous(name):
                raise ReadOnlyViolationError(f"function not on the allow list: {name}")
        if (
            isinstance(node, exp.Literal)
            and node.is_string
            and node.find_ancestor(exp.Func) is not None
            and _EMBEDDED_WRITE.match(node.this)
        ):
            raise ReadOnlyViolationError("function argument carries a write statement")


def assert_safe_http_method(method: str) -> str:
    normalised = method.upper()
    if normalised not in SAFE_HTTP_METHODS:
        raise ReadOnlyViolationError(f"unsafe HTTP method: {normalised}")
    return normalised
