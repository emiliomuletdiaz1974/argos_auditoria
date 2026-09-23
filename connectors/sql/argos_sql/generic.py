"""Generic SQL connector (SQLAlchemy): read-only sessions and dialect-compiled probes (ARG-014)."""

import copy
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    ColumnElement,
    Engine,
    Integer,
    String,
    TableClause,
    bindparam,
    cast,
    column,
    create_engine,
    event,
    func,
    inspect,
    literal,
    select,
    table,
    text,
)
from sqlalchemy.engine import Connection, Dialect, Row, make_url
from sqlalchemy.engine.interfaces import BindTyping
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.types import NullType

from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec
from argos_connector.tls import require_tls
from argos_connector.validators import acceptance_rates, resolve_validators

SQLGLOT_DIALECTS = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "mssql": "tsql",
    "oracle": "oracle",
    "sqlite": "sqlite",
}
EXCLUDED_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "pg_toast", "sys", "mysql", "performance_schema"}
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]{0,127}$")


@dataclass(frozen=True, slots=True)
class ConfigCheck:
    """A named configuration check: literal read-only SQL and the parameter names it binds."""

    sql: str
    params: tuple[str, ...] = ()


# The casts a challenge may ask for before comparing; nothing else reaches a statement.
_FILTER_CASTS: Mapping[str, Any] = {"text": String}
# What a challenge may compare a column with; nothing else reaches a statement.
_FILTER_OPERATORS: Mapping[str, Callable[[Any, Any], Any]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}


def transport_encrypted(raw_url: str) -> bool:
    """Whether the URL asks for a transport that is encrypted **and** checks the server.

    Encryption without verification (PostgreSQL `sslmode=require`) sends the samples to whoever
    answers, so it does not count. SQLite is a local file and has no transport.
    """
    url = make_url(raw_url)
    query = {key.lower(): str(value).lower() for key, value in url.query.items()}
    backend = url.get_backend_name()
    if backend == "sqlite":
        return True
    if backend == "postgresql":
        return query.get("sslmode") in ("verify-ca", "verify-full")
    if backend in ("mysql", "mariadb"):
        return "ssl_ca" in query
    if backend == "mssql":
        return query.get("encrypt") in ("yes", "true", "strict", "mandatory")
    if backend == "oracle":
        return query.get("protocol") == "tcps" or "(protocol=tcps)" in raw_url.lower()
    return False


def _identifier(name: str) -> str:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(bytes(value))} bytes>"
    return str(value)


def driver_options(url: Any, timeout_ms: int) -> dict[str, Any]:
    """What the driver itself needs to stop waiting (SEC-006, review F09-02).

    PostgreSQL, MySQL and Oracle get their deadline in the session; pymssql has none by default
    and takes it only when connecting, in whole seconds.
    """
    if url.get_backend_name() == "mssql" and url.get_driver_name() == "pymssql":
        seconds = max(1, round(timeout_ms / 1000))
        return {"connect_args": {"timeout": seconds, "login_timeout": seconds}}
    return {}


class SqlConnector(Connector):
    kind = "rdbms"
    CONFIG_CHECKS: ClassVar[Mapping[str, ConfigCheck]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._engine: Engine | None = None
        self._compile_dialect: Dialect | None = None
        self._dialect_name = ""

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._engine

    @property
    def compile_dialect(self) -> Dialect:
        if self._compile_dialect is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._compile_dialect

    @property
    def statement_timeout_ms(self) -> int:
        return int(self.config.get("statement_timeout_ms", 30_000))

    # ---------- lifecycle ----------
    def open(self) -> None:
        raw_url = self.context.credentials["url"]
        url = make_url(raw_url)
        require_tls(transport_encrypted(raw_url), self.config, url.render_as_string())
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.get_backend_name() != "sqlite":
            options.update(pool_size=1, max_overflow=1, pool_recycle=1800)
        options.update(driver_options(url, self.statement_timeout_ms))
        if "isolation_level" in self.config:
            options["isolation_level"] = self.config["isolation_level"]
        engine = create_engine(url, **options)
        self._dialect_name = engine.dialect.name
        event.listen(engine, "connect", self._on_connect)
        if self._dialect_name == "oracle":
            event.listen(engine, "begin", self._on_begin)
        with engine.connect():  # learn the server version before compiling any statement
            pass
        dialect = copy.copy(engine.dialect)
        dialect.paramstyle = "named"
        dialect.positional = False
        # psycopg renders a cast beside a typed bind (":filter_0::VARCHAR"); the compiled
        # string is executed through text(), which would no longer recognise the bind.
        dialect.bind_typing = BindTyping.NONE
        self._engine, self._compile_dialect = engine, dialect

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = self._compile_dialect = None

    def statement_dialect(self) -> str:
        return SQLGLOT_DIALECTS[self.engine.dialect.name]

    # ---------- read-only sessions, on every pooled connection ----------
    def _on_connect(self, dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in self._session_statements(cursor):
                cursor.execute(statement)
        finally:
            cursor.close()
        dbapi_connection.commit()  # PostgreSQL SET is transactional: survive the pool rollback
        if self._dialect_name == "oracle":
            dbapi_connection.call_timeout = self.statement_timeout_ms

    def _session_statements(self, cursor: Any) -> list[str]:
        timeout = self.statement_timeout_ms
        if self._dialect_name == "postgresql":
            return [
                "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
                f"SET statement_timeout = {timeout}",
                "SET lock_timeout = 1000",
            ]
        if self._dialect_name in ("mysql", "mariadb"):
            cursor.execute("SELECT VERSION()")
            version = str(cursor.fetchone()[0]).lower()
            limit = (
                f"SET SESSION max_statement_time = {timeout / 1000:.3f}"
                if "mariadb" in version
                else f"SET SESSION max_execution_time = {timeout}"
            )
            return ["SET SESSION TRANSACTION READ ONLY", limit]
        if self._dialect_name == "mssql":
            return ["SET LOCK_TIMEOUT 1000"]  # the db_datareader account is the guarantee here
        if self._dialect_name == "sqlite":
            return ["PRAGMA query_only = ON"]
        return []

    @staticmethod
    def _on_begin(connection: Connection) -> None:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")  # Oracle: per transaction

    # ---------- rendering: the journaled text is the executed text ----------
    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "count":
            return self._compiled(spec, self._count_statement(spec))
        if spec.kind == "sample":
            self._sample_validators(spec)  # unknown validators are refused before journaling
            return self._compiled(spec, self._sample_statement(spec))
        if spec.kind == "check_config":
            name = spec.params.get("check")
            if name is not None:
                check = self.CONFIG_CHECKS.get(name)
                if check is None:
                    raise ValueError(f"unknown configuration check: {name!r}")
                binds = {param: spec.params[param] for param in check.params}
                return replace(spec, statement=check.sql, params={**spec.params, "binds": binds})
            if not spec.statement:
                raise ValueError("check_config needs a named check or a declared statement")
        return spec

    def _compiled(self, spec: ProbeSpec, statement: Select[Any]) -> ProbeSpec:
        compiled = statement.compile(
            dialect=self.compile_dialect, compile_kwargs={"render_postcompile": True}
        )
        binds = {**compiled.params, **dict(spec.params.get("binds", {}))}
        return replace(spec, statement=compiled.string, params={**spec.params, "binds": binds})

    def _table(self, target: str, columns: list[str]) -> TableClause:
        parts = target.split(".")
        if len(parts) > 2:
            raise ValueError(f"invalid SQL identifier: {target!r}")
        name = _identifier(parts[-1])
        schema = _identifier(parts[0]) if len(parts) == 2 else None
        return table(name, *[column(_identifier(c)) for c in columns], schema=schema)

    def _count_statement(self, spec: ProbeSpec) -> Select[Any]:
        filters = list(spec.params.get("filters") or [])
        columns = [str(entry.get("column", "")) for entry in filters]
        source = self._table(spec.target, columns)
        statement = select(func.count().label("n")).select_from(source)
        for index, entry in enumerate(filters):
            statement = statement.where(self._filter(source, index, entry))
        where = spec.params.get("where")  # templates from the challenge library only
        return statement.where(text(where)) if where else statement

    @staticmethod
    def _filter(source: TableClause, index: int, entry: Mapping[str, Any]) -> ColumnElement[bool]:
        """A comparison the challenge declared: the column is an identifier, the value a bind.

        This is how a challenge probes the node it was compiled for without ever formatting a
        value into a statement: the name of a column cannot travel as a parameter, so it is
        validated as an identifier, and everything else is bound.
        """
        name = _identifier(str(entry.get("column", "")))
        operator = str(entry.get("operator", "=="))
        comparison = _FILTER_OPERATORS.get(operator)
        if comparison is None:
            raise ValueError(f"unknown filter operator: {operator!r}")
        wanted = entry.get("cast")
        if wanted is not None and str(wanted) not in _FILTER_CASTS:
            raise ValueError(f"unknown filter cast: {wanted!r}")
        # Untyped on purpose: with a type, psycopg renders the cast ":filter_0::VARCHAR" and
        # text() would no longer recognise the bind when the compiled string is executed.
        bind: BindParameter[Any] = bindparam(
            f"filter_{index}", entry.get("value"), type_=NullType()
        )
        # A challenge may ask for the comparison as text: looking for an identifier in every
        # column of a table means meeting columns of other types, and a type clash is not a
        # finding. The cast is declared, never guessed.
        left: Any = source.c[name]
        if wanted is not None:
            left = cast(left, _FILTER_CASTS[str(wanted)])
        condition: ColumnElement[bool] = comparison(left, bind)
        return condition

    def _sample_statement(self, spec: ProbeSpec) -> Select[Any]:
        columns = list(spec.params.get("columns") or [])
        if not columns:
            raise ValueError("sample needs at least one column")
        source = self._table(spec.target, columns)
        limit = min(int(spec.params.get("k", 100)), self.context.budget.max_rows_per_probe)
        # Rendered inline as an integer: psycopg casts bound limits (":param_1::INTEGER"), which
        # text() would no longer recognise as a bind once the compiled string is executed.
        rendered_limit = literal(limit, type_=Integer, literal_execute=True)
        return select(*[source.c[c] for c in columns]).select_from(source).limit(rendered_limit)

    def _sample_validators(self, spec: ProbeSpec) -> dict[str, Callable[[object], bool]]:
        names = [str(name) for name in spec.params.get("validators", [])]
        pattern = self.config.get("mrn_pattern")
        return resolve_validators(names, str(pattern) if pattern else None)

    # ---------- probes ----------
    def _rows(self, spec: ProbeSpec) -> list[Row[Any]]:
        if spec.statement is None:
            raise ValueError("probe has no statement")
        with self.engine.connect() as connection:
            binds = dict(spec.params.get("binds", {}))
            return list(connection.execute(text(spec.statement), binds))

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        inspector = inspect(self.engine)
        wanted = set(spec.params.get("schemas", []))
        schemas: dict[str, dict[str, Any]] = {}
        columns_seen = 0
        for schema in inspector.get_schema_names():
            if schema.lower() in EXCLUDED_SCHEMAS or (wanted and schema not in wanted):
                continue
            tables: dict[str, Any] = {}
            for table_name in inspector.get_table_names(schema=schema):
                columns = [
                    {"name": c["name"], "type": str(c["type"]), "nullable": bool(c["nullable"])}
                    for c in inspector.get_columns(table_name, schema=schema)
                ]
                tables[table_name] = {"columns": columns}
                columns_seen += len(columns)
            schemas[schema] = tables
        return {"schemas": schemas}, columns_seen

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        n = int(self._rows(spec)[0][0])
        return {"count": n}, n

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        rows = self._rows(spec)
        hasher = self.context.hasher
        digests = [[hasher.digest(value) for value in row] for row in rows]  # never clear values
        columns = list(spec.params["columns"])
        data: dict[str, Any] = {"columns": columns, "n": len(rows), "cell_digests": digests}
        validators = self._sample_validators(spec)
        if validators:  # validated in memory: only acceptance rates leave the connector
            rates: dict[str, dict[str, float]] = {}
            validated: dict[str, int] = {}
            for index, column_name in enumerate(columns):
                rates[column_name], validated[column_name] = acceptance_rates(
                    (row[index] for row in rows), validators
                )
            data["validator_rates"] = rates
            data["validated"] = validated
        return data, len(rows)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        rows = [{k: _jsonable(v) for k, v in row._mapping.items()} for row in self._rows(spec)]
        return {"rows": rows}, len(rows)
