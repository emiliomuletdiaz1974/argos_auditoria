"""ADR-0006 · the jurist's Spanish field names are translated, never leaked into the core."""

import pytest

from argos_ontology.editorial.translation import (
    EDITORIAL_KEYS,
    INTERNAL_KEYS,
    read_editorial,
    to_editorial,
    to_internal,
)

TEMPLATE = """
id: OBL-RGPD-5-1-E
norma: RGPD
articulo: "5.1.e"
titulo: Limitación del plazo de conservación
vigente_desde: 2018-05-25
severidad: high
aplica_a: [AC-stored-personal-data]
verificado_por: [ret-table-retention]
"""


def test_the_mapping_is_one_to_one_and_the_core_side_is_english() -> None:
    assert len(set(EDITORIAL_KEYS.values())) == len(EDITORIAL_KEYS)
    assert {INTERNAL_KEYS[v] for v in EDITORIAL_KEYS.values()} == set(EDITORIAL_KEYS)
    assert all(key.isascii() and key == key.lower() for key in EDITORIAL_KEYS.values())


def test_round_trip_between_editorial_and_internal_fields() -> None:
    editorial = read_editorial(TEMPLATE)
    internal = to_internal(editorial)
    assert set(internal) == {
        "id",
        "norm",
        "article",
        "title",
        "in_force_from",
        "severity",
        "applies_to",
        "verified_by",
    }
    assert to_editorial(internal) == editorial


def test_unknown_editorial_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown editorial fields: \\['gravedad'\\]"):
        to_internal({"id": "OBL-X-1", "gravedad": "alta"})


def test_internal_keys_cannot_be_used_in_the_editorial_template() -> None:
    with pytest.raises(ValueError, match="unknown editorial fields"):
        to_internal({"id": "OBL-X-1", "severity": "high"})


def test_unknown_internal_fields_are_rejected_on_the_way_back() -> None:
    with pytest.raises(ValueError, match="unknown internal fields"):
        to_editorial({"id": "OBL-X-1", "severidad": "high"})


def test_repeated_fields_are_rejected_instead_of_keeping_the_last() -> None:
    with pytest.raises(ValueError, match="duplicate editorial field: 'severidad'"):
        read_editorial("id: OBL-X-1\nseveridad: high\nseveridad: low\n")


@pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n", ""])
def test_a_template_must_be_a_mapping(text: str) -> None:
    with pytest.raises(ValueError, match="mapping of fields"):
        read_editorial(text)
