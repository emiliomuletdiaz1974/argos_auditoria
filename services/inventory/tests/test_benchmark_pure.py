"""Capacity benchmark · profiles, synthetic metadata and the report arithmetic (pure)."""

import pytest

from argos_inventory.benchmark import (
    BASE_COLUMNS,
    CONNECTOR,
    PROFILES,
    hours_for,
    pass_tables,
    percentile,
    synthetic_columns,
    table_event,
)


def test_m_profile_matches_the_capacity_target() -> None:
    m = PROFILES["m"]
    assert (m.systems, m.tables) == (200, 50_000)
    assert m.changed_per_system == 3


@pytest.mark.parametrize("count", [6, 12, 15])
def test_synthetic_columns_are_deterministic_and_unique(count: int) -> None:
    columns = synthetic_columns(7, count)
    names = [c["name"] for c in columns]
    assert len(names) == len(set(names)) == count
    assert columns == synthetic_columns(7, count)
    assert all(c["type"] == "text" and c["nullable"] is True for c in columns)
    if count > len(BASE_COLUMNS):
        assert names[-1] == f"attribute_{count - len(BASE_COLUMNS) - 1}"


def test_dictionary_hits_are_present() -> None:
    names = [c["name"] for c in synthetic_columns(0, 6)]
    assert names == ["id", "national_id", "full_name", "birth_date", "email", "diagnosis_code"]


def test_second_pass_replaces_the_changed_tables() -> None:
    smoke = PROFILES["smoke"]
    first, second = pass_tables(smoke, 1), pass_tables(smoke, 2)
    assert first == list(range(25))
    assert len(second) == 25
    assert set(first) - set(second) == {0}
    assert set(second) - set(first) == {25}


def test_there_are_exactly_two_passes() -> None:
    with pytest.raises(ValueError, match="two passes"):
        pass_tables(PROFILES["smoke"], 3)


def test_percentile_uses_the_nearest_rank() -> None:
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.5) == 2.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.95) == 4.0
    with pytest.raises(ValueError, match="no values"):
        percentile([], 0.5)


def test_hours_are_extrapolated_to_the_target_tables() -> None:
    assert hours_for(100, 36.0) == 5.0
    with pytest.raises(ValueError, match="positive"):
        hours_for(0, 1.0)


def test_table_event_matches_the_scanner_contract() -> None:
    event = table_event("sys", "run", 42, 3, "2026-09-15T10:00:00+00:00", 9)
    assert set(event) == {
        "system_id",
        "run_id",
        "source_connector",
        "probe_id",
        "journal_seq",
        "observed_at",
        "schema",
        "table",
        "est_rows",
        "bytes",
        "comment",
        "columns",
    }
    assert (event["table"], event["source_connector"], len(event["columns"])) == (
        "table_00042",
        CONNECTOR,
        3,
    )
