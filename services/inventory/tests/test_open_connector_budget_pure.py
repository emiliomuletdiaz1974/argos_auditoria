"""SEC-004 · every connector of a system is opened with that system's shared budget."""

from typing import Any, cast

import pytest

from argos_connector.base import Connector
from argos_connector.budget_pg import PostgresBudgetStore
from argos_inventory.discovery import probes
from argos_inventory.discovery.probes import RegisteredSystem, open_connector


class Idle(Connector):
    kind = "test.idle"

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def _nothing(self, spec: Any) -> tuple[dict[str, Any], int]:
        return {}, 0

    _do_scan_schema = _do_count = _do_sample = _do_check_config = _nothing


def test_the_budget_of_a_connector_is_the_system_s(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "connector_class", lambda path: Idle)
    monkeypatch.setattr(probes, "load_credentials", lambda store, sid: {"hash_key": "00" * 32})
    heard: list[Any] = []
    system = RegisteredSystem(
        "01920000-0000-7000-8000-00000000c001",
        "ERP",
        "rdbms",
        "argos_sql.x:Y",
        {"budget": {"queries_per_minute": 5}},
    )
    connector = open_connector(
        "postgresql://unused", cast(Any, object()), system, lambda sid, p50: heard.append(sid)
    )
    budget: Any = connector.context.budget
    assert isinstance(budget._store, PostgresBudgetStore)
    assert budget._on_open is not None
    budget._on_open(system.id, 10.0)
    assert heard == [system.id]
