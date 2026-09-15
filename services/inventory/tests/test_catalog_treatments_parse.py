"""ARG-026 · parsing of the DPO record of processing activities (CSV, pure)."""

import pytest

from argos_inventory.catalog.treatments import TREATMENT_HEADERS, TreatmentRow, parse_treatments

GOOD = (
    "id;name;legal_basis;retention;systems\n"
    "T-001;Synthetic clinical record;GDPR 9.2.h;15 years;dev-source-postgres, dev-files-local\n"
    "T-002;Synthetic billing;GDPR 6.1.b;6 years;\n"
)


def test_parses_rows_and_splits_systems() -> None:
    rows = parse_treatments(GOOD.encode("utf-8"))
    assert rows == [
        TreatmentRow(
            "T-001",
            "Synthetic clinical record",
            "GDPR 9.2.h",
            "15 years",
            ("dev-source-postgres", "dev-files-local"),
        ),
        TreatmentRow("T-002", "Synthetic billing", "GDPR 6.1.b", "6 years", ()),
    ]
    assert TREATMENT_HEADERS == ("id", "name", "legal_basis", "retention", "systems")


def test_accepts_a_utf8_byte_order_mark() -> None:
    assert len(parse_treatments(b"\xef\xbb\xbf" + GOOD.encode("utf-8"))) == 2


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("id;nombre;base_juridica;plazo_conservacion;sistemas\nT-1;x;y;z;\n", "headers"),
        ("id;name;legal_basis;retention;systems\n;x;y;z;\n", "empty id"),
        ("id;name;legal_basis;retention;systems\nT-1;x;y;z;\nT-1;x;y;z;\n", "duplicate"),
        ("", "headers"),
    ],
)
def test_rejects_malformed_files(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_treatments(text.encode("utf-8"))
