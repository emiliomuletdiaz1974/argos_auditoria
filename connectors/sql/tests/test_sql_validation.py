"""SqlConnector sample with in-memory validators (ARG-024): only acceptance rates leave."""

import sqlite3
from pathlib import Path

import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.testing import InMemoryJournal, make_context
from argos_sql.generic import SqlConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
IBAN = "ES5799990001000000000001"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "documents.db"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "CREATE TABLE documents "
            "(id INTEGER PRIMARY KEY, dni_number TEXT, iban TEXT, record TEXT)"
        )
        conn.executemany(
            "INSERT INTO documents VALUES (?, ?, ?, ?)",
            [
                (1, "99990001P", IBAN, "HC-000001"),
                (2, "99991000H", IBAN, "HC-000002"),
                (3, "99990001A", "not-an-iban", "HC-X"),
                (4, None, None, None),
            ],
        )
    conn.close()
    return path


def _open(db: Path, **config: object) -> tuple[SqlConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    context = make_context({"url": f"sqlite:///{db.as_posix()}"}, journal=journal)
    connector = SqlConnector(SYSTEM_ID, {"statement_timeout_ms": 5000, **config}, context)
    connector.open()
    return connector, journal


def test_sample_returns_rates_per_column_and_never_values(db: Path) -> None:
    connector, _ = _open(db)
    params = {"columns": ["dni_number", "iban"], "k": 10, "validators": ["dni", "iban_es"]}
    result = connector.execute(ProbeSpec("sample", "documents", params=params))
    rates = result.data["validator_rates"]
    assert rates == {
        "dni_number": {"dni": 0.6667, "iban_es": 0.0},
        "iban": {"dni": 0.0, "iban_es": 0.6667},
    }
    assert result.data["validated"] == {"dni_number": 3, "iban": 3}
    text = repr(result)
    assert "99990001P" not in text and IBAN not in text


def test_journal_records_the_requested_validators(db: Path) -> None:
    connector, journal = _open(db)
    params = {"columns": ["dni_number"], "k": 5, "validators": ["dni"]}
    connector.execute(ProbeSpec("sample", "documents", params=params))
    assert journal.emitted[0].spec.params["validators"] == ["dni"]


def test_medical_record_numbers_use_the_system_pattern(db: Path) -> None:
    connector, _ = _open(db, mrn_pattern=r"HC-\d{6}")
    params = {"columns": ["record"], "k": 10, "validators": ["mrn"]}
    result = connector.execute(ProbeSpec("sample", "documents", params=params))
    assert result.data["validator_rates"] == {"record": {"mrn": 0.6667}}


@pytest.mark.parametrize(
    ("validators", "config", "message"),
    [(["passport"], {}, "unknown validator"), (["mrn"], {}, "configured pattern")],
)
def test_invalid_validators_are_refused_before_journaling(
    db: Path, validators: list[str], config: dict[str, object], message: str
) -> None:
    connector, journal = _open(db, **config)
    params = {"columns": ["dni_number"], "k": 5, "validators": validators}
    with pytest.raises(ValueError, match=message):
        connector.execute(ProbeSpec("sample", "documents", params=params))
    assert journal.records == []


def test_sample_without_validators_is_unchanged(db: Path) -> None:
    connector, _ = _open(db)
    spec = ProbeSpec("sample", "documents", params={"columns": ["id"], "k": 2})
    result = connector.execute(spec)
    assert "validator_rates" not in result.data and result.data["n"] == 2
