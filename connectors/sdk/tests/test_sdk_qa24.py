"""QA-24 · validators, the probe window and the read-only validator at their edges.

- QA-017: blank values are not wrong values; identifiers written with separators or without the
  leading zero are still identifiers; digits that are not ASCII are not digits of a DNI.
- QA-018: an overnight window (22:00 to 06:00) is open at night, on the days it starts.
- QA-019: a statement that does not even tokenise is a read-only violation, like any other refusal.
- QA-023: a backslash means different things to the validator and to some server modes: refused.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from argos_common.errors import ReadOnlyViolationError
from argos_connector.budget import Window, parse_windows, window_open
from argos_connector.config_sources import check_config_sources
from argos_connector.readonly import validate_read_only_sql
from argos_connector.validators import (
    VALIDATORS,
    acceptance_rates,
    is_valid_dni,
    is_valid_iban_es,
    is_valid_nie,
)

MADRID = ZoneInfo("Europe/Madrid")


def test_blank_values_do_not_lower_the_acceptance_rate() -> None:
    rates, present = acceptance_rates(["12345678Z", "", "  ", None], {"dni": VALIDATORS["dni"]})
    assert rates == {"dni": 1.0} and present == 1


@pytest.mark.parametrize("value", ["12345678-Z", "12.345.678-Z", "12345678 Z", "1234567L"])
def test_a_dni_written_with_separators_or_without_its_leading_zero_is_a_dni(value: str) -> None:
    assert is_valid_dni(value)


def test_a_nie_with_separators_is_a_nie() -> None:
    assert is_valid_nie("X-1234567-L")


@pytest.mark.parametrize("value", ["１２３４５６７８Z", "١٢٣٤٥٦٧٨Z"])
def test_digits_that_are_not_ascii_are_not_a_dni(value: str) -> None:
    assert not is_valid_dni(value)


def test_an_iban_with_fullwidth_digits_is_not_an_iban() -> None:
    assert is_valid_iban_es("ES9121000418450200051332")
    assert not is_valid_iban_es("ES９１21000418450200051332")


def _at(day: int, hour: int, minute: int = 30) -> dt.datetime:
    return dt.datetime(2026, 9, day, hour, minute, tzinfo=MADRID)  # 28 Sep 2026 is a Monday


def test_an_overnight_window_is_open_at_night() -> None:
    [window] = parse_windows([{"days": "mon-fri", "from": "22:00", "to": "06:00"}])
    assert window_open((window,), _at(28, 23))  # Monday night
    assert window_open((window,), _at(29, 2))  # early Tuesday: Monday's window
    assert not window_open((window,), _at(29, 12))
    # Saturday 02:30 belongs to Friday's window; Sunday 02:30 to Saturday's, which does not exist.
    assert window_open((window,), _at(26, 2)) is True  # Saturday 26 Sep, after Friday night
    assert window_open((window,), _at(27, 2)) is False


def test_a_day_window_still_works() -> None:
    window = Window(frozenset({0}), dt.time(9, 0), dt.time(17, 0))
    assert window_open((window,), _at(28, 10))
    assert not window_open((window,), _at(28, 18))


@pytest.mark.parametrize("statement", ["SELECT 'abc", "SELECT $$abc", 'SELECT "abc'])
def test_a_statement_that_does_not_tokenise_is_a_read_only_violation(statement: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql(statement, "postgres")
    with pytest.raises(ValueError):
        check_config_sources(statement, "postgres")


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT '\\'; DELETE FROM t; -- '", "mysql"),
        ("SELECT 'x\\' AS a, ' ; DELETE FROM t; -- '", "postgres"),
    ],
)
def test_a_backslash_is_refused_where_server_modes_change_its_meaning(
    statement: str, dialect: str
) -> None:
    with pytest.raises(ReadOnlyViolationError, match="backslash"):
        validate_read_only_sql(statement, dialect)
