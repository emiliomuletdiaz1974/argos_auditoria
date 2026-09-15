"""Connector base contract (ARG-011): journal first, budget, minimal errors, final execute()."""

import uuid
from dataclasses import replace
from typing import Any

import pytest

from argos_common.errors import ReadOnlyViolationError
from argos_connector.base import Connector
from argos_connector.errors import BudgetExceededError
from argos_connector.probes import ProbeResult, ProbeSpec
from argos_connector.testing import (
    SQL_WRITE_ATTEMPTS,
    InMemoryJournal,
    NoBudget,
    assert_no_write_surface,
    assert_sql_writes_rejected,
    make_context,
)


class RecordingConnector(Connector):
    kind = "test"
    sql_dialect = "postgres"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[ProbeSpec] = []
        self.emitted_when_called: list[int] = []
        self.fail_with: Exception | None = None

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "count" and spec.statement is None:
            return replace(spec, statement=f"SELECT count(*) AS n FROM {spec.target}")  # noqa: S608
        return spec

    def _probe(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        journal = self.context.journal
        assert isinstance(journal, InMemoryJournal)
        self.emitted_when_called.append(len(journal.emitted))
        self.calls.append(spec)
        if self.fail_with is not None:
            raise self.fail_with
        return {"target": spec.target}, 3

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._probe(spec)

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._probe(spec)

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._probe(spec)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return self._probe(spec)


def _connector(budget: NoBudget | None = None) -> tuple[RecordingConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    context = make_context(journal=journal, budget=budget or NoBudget())
    return RecordingConnector("0190f000-0000-7000-8000-000000000001", {}, context), journal


def test_journal_entry_exists_before_the_system_is_touched() -> None:
    connector, journal = _connector()
    result = connector.execute(ProbeSpec("scan_schema", "public"))
    assert connector.emitted_when_called == [1]
    assert isinstance(result, ProbeResult)
    assert result.ok and result.rows_touched == 3 and result.journal_seq == 1
    assert uuid.UUID(result.probe_id).version == 7
    assert journal.records[0].outcome == {
        "ok": True,
        "duration_ms": result.duration_ms,
        "rows": 3,
        "error": None,
    }


def test_rendered_statement_is_what_gets_journaled() -> None:
    connector, journal = _connector()
    connector.execute(ProbeSpec("count", "clinic.patients"))
    assert journal.emitted[0].spec.statement == "SELECT count(*) AS n FROM clinic.patients"
    assert connector.calls[0].statement == journal.emitted[0].spec.statement


def test_rejected_statement_is_journaled_and_never_executed() -> None:
    connector, journal = _connector()
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("check_config", "t", "DELETE FROM t"))
    assert connector.calls == []
    assert journal.emitted == []
    assert [r.action for r in journal.records] == ["query.reject"]


def test_hook_errors_are_reported_by_type_only() -> None:
    connector, journal = _connector()
    connector.fail_with = ValueError("duplicate key national_id=12345678Z")
    result = connector.execute(ProbeSpec("sample", "clinic.patients"))
    assert not result.ok and result.rows_touched == 0
    assert result.data == {"error": "ValueError"}
    assert "12345678Z" not in repr(result)
    outcome = journal.records[0].outcome
    assert outcome is not None and outcome["ok"] is False and outcome["error"] == "ValueError"


def test_budget_refusal_closes_the_journal_row_and_skips_the_probe() -> None:
    connector, journal = _connector(NoBudget(fail_with=BudgetExceededError("outside window")))
    with pytest.raises(BudgetExceededError):
        connector.execute(ProbeSpec("count", "t"))
    assert connector.calls == []
    outcome = journal.records[0].outcome
    assert outcome is not None and outcome["error"] == "BUDGET_EXCEEDED"


def test_latency_is_reported_to_the_budget() -> None:
    budget = NoBudget()
    connector, _ = _connector(budget)
    result = connector.execute(ProbeSpec("scan_schema", "public"))
    assert budget.latencies == [result.duration_ms]


def test_unknown_probe_kind_is_a_programming_error() -> None:
    connector, journal = _connector()
    with pytest.raises(ValueError, match="probe kind"):
        connector.execute(ProbeSpec("delete_everything", "t"))
    assert journal.records == []


def test_execute_cannot_be_overridden() -> None:
    with pytest.raises(TypeError, match="execute"):

        class Sneaky(RecordingConnector):
            def execute(self, spec: ProbeSpec) -> ProbeResult:  # type: ignore[misc]
                raise NotImplementedError


def test_write_harness_rejects_every_sql_attempt() -> None:
    connector, journal = _connector()
    assert_sql_writes_rejected(connector)
    assert len(journal.records) == len(SQL_WRITE_ATTEMPTS)
    assert all(r.action == "query.reject" for r in journal.records)
    assert connector.calls == []


def test_write_surface_detection() -> None:
    assert_no_write_surface(RecordingConnector)

    class Leaky(RecordingConnector):
        def insert_rows(self) -> None: ...

    with pytest.raises(AssertionError, match="insert_rows"):
        assert_no_write_surface(Leaky)
