"""ARGOS connector SDK: read-only contract by construction (ARG-011)."""

import abc
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, ClassVar, Self, final

from argos_common.errors import ReadOnlyViolationError
from argos_common.ids import uuid7
from argos_common.logs import get_logger

from .context import ConnectorContext
from .errors import BudgetExceededError, CircuitOpenError
from .probes import PROBE_KINDS, ProbeResult, ProbeSpec
from .readonly import validate_read_only_sql

Handler = Callable[[ProbeSpec], tuple[dict[str, Any], int]]
_log = get_logger(__name__, "ARG-011")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


class Connector(abc.ABC):
    """Base of every connector. Subclasses implement the _do_* hooks and never execute()."""

    kind: ClassVar[str] = "abstract"
    sql_dialect: ClassVar[str | None] = None  # sqlglot dialect; None when statements are not SQL

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "execute" in cls.__dict__:
            raise TypeError(f"{cls.__name__} must not override execute()")

    def __init__(
        self, system_id: str, config: Mapping[str, Any], context: ConnectorContext
    ) -> None:
        self.system_id = system_id
        self.config = dict(config)
        self.context = context

    # ---------- lifecycle ----------
    def open(self) -> None:
        """Open sessions in read-only mode where the protocol supports it."""
        return None

    def close(self) -> None:
        """Release sessions."""
        return None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- hooks around the single entry point ----------
    def render(self, spec: ProbeSpec) -> ProbeSpec:
        """Materialise the literal statement that will be journaled and sent."""
        return spec

    def statement_dialect(self) -> str | None:
        return self.sql_dialect

    def validate(self, spec: ProbeSpec) -> None:
        if spec.kind not in PROBE_KINDS:
            raise ValueError(f"unknown probe kind: {spec.kind!r}")
        dialect = self.statement_dialect()
        if spec.statement is not None and dialect is not None:
            validate_read_only_sql(spec.statement, dialect)

    @final
    def execute(self, spec: ProbeSpec) -> ProbeResult:
        journal = self.context.journal
        try:
            rendered = self.render(spec)
            self.validate(rendered)
        except ReadOnlyViolationError as exc:
            journal.reject(spec, exc.message)
            raise
        seq = journal.register(rendered)  # 1) journal BEFORE touching the customer system
        try:
            self.context.budget.acquire()  # 2) budget: waits, or refuses
        except (BudgetExceededError, CircuitOpenError) as exc:
            journal.complete(seq, ok=False, duration_ms=0, rows=0, error=exc.code)
            raise
        started = time.monotonic()
        error: str | None = None
        try:
            data, rows = self._handler(rendered.kind)(rendered)
        except ReadOnlyViolationError as exc:
            journal.complete(
                seq, ok=False, duration_ms=_elapsed_ms(started), rows=0, error=exc.code
            )
            raise
        except Exception as exc:  # the driver message may carry customer data: report the type only
            error = type(exc).__name__
            data, rows = {"error": error}, 0
            _log.warning("probe failed", extra={"journal_seq": seq, "trace_id": error})
        duration = _elapsed_ms(started)
        self.context.budget.observe_latency(duration)  # 3) feeds the circuit breaker
        journal.complete(seq, ok=error is None, duration_ms=duration, rows=rows, error=error)
        return ProbeResult(str(uuid7()), rendered.kind, error is None, data, duration, rows, seq)

    @contextmanager
    def follow_up(self, spec: ProbeSpec) -> Iterator[None]:
        """A further request to the system inside one probe, or when opening the connector.

        A page the server hands out, or the association a protocol needs, is still a request to
        the customer system: it is journaled before it is sent and it pays its permit from the
        load budget, like the probe itself (security review F09-02, SEC-023).
        """
        journal = self.context.journal
        seq = journal.register(spec)
        try:
            self.context.budget.acquire()
        except (BudgetExceededError, CircuitOpenError) as exc:
            journal.complete(seq, ok=False, duration_ms=0, rows=0, error=exc.code)
            raise
        started = time.monotonic()
        try:
            yield
        except Exception as exc:
            journal.complete(
                seq, ok=False, duration_ms=_elapsed_ms(started), rows=0, error=type(exc).__name__
            )
            raise
        duration = _elapsed_ms(started)
        self.context.budget.observe_latency(duration)
        journal.complete(seq, ok=True, duration_ms=duration, rows=0)

    def _handler(self, kind: str) -> Handler:
        handlers: dict[str, Handler] = {
            "scan_schema": self._do_scan_schema,
            "count": self._do_count,
            "sample": self._do_sample,
            "check_config": self._do_check_config,
        }
        return handlers[kind]

    # ---------- hooks each connector implements ----------
    @abc.abstractmethod
    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]: ...

    @abc.abstractmethod
    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]: ...

    @abc.abstractmethod
    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]: ...

    @abc.abstractmethod
    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]: ...
