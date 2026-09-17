"""ARG-041 · the Spanish layer translates to the English core and back (ADR-0007, F05-00)."""

import pytest

from argos_challenges.library.translation import (
    CHALLENGE_KEYS,
    CHALLENGE_VALUES,
    TranslationError,
    read_challenge,
    to_editorial,
    to_internal,
)

SPANISH = """
id: ret-table-retention
version: "1.0"
titulo: Retención efectiva en tabla frente al calendario declarado
objetivo:
  obligacion: OBL-RGPD-5-1
selector:
  clase_de_activo: AC-stored-personal-data
sonda:
  kind: count
  por_conector:
    rdbms.postgresql:
      statement: SELECT count(*) FROM patients
criterio:
  opa:
    paquete: argos.retention
evidencia:
  capturar: [recuentos]
  minimizacion: Solo el recuento de registros fuera de plazo y los parámetros del cálculo.
severidad: alta
muestreo:
  confianza: 0.95
  margen: 0.05
aprobacion_requerida: false
"""


def test_keys_and_values_are_closed_and_injective() -> None:
    assert len(set(CHALLENGE_KEYS.values())) == len(CHALLENGE_KEYS)
    for field, table in CHALLENGE_VALUES.items():
        assert len(set(table.values())) == len(table), field


def test_a_spanish_challenge_becomes_english_keys_and_values() -> None:
    internal = to_internal(read_challenge(SPANISH))
    assert internal["objective"] == {"obligation": "OBL-RGPD-5-1"}
    assert internal["selector"] == {"asset_class": "AC-stored-personal-data"}
    assert internal["probe"]["by_connector"]["rdbms.postgresql"]["statement"].startswith("SELECT")
    assert internal["criterion"] == {"opa": {"package": "argos.retention"}}
    assert internal["evidence"]["capture"] == ["counts"]
    assert internal["severity"] == "high"
    assert internal["sampling"] == {"confidence": 0.95, "margin": 0.05}
    assert internal["approval_required"] is False


def test_a_challenge_already_in_english_is_left_alone() -> None:
    english = to_internal(read_challenge(SPANISH))
    assert to_internal(english) == english


def test_the_round_trip_is_the_identity() -> None:
    internal = to_internal(read_challenge(SPANISH))
    assert to_internal(to_editorial(internal)) == internal


def test_an_unknown_key_is_an_error_never_ignored() -> None:
    with pytest.raises(TranslationError, match="objetivos"):
        to_internal({"id": "ret-x", "objetivos": {"obligacion": "OBL-RGPD-5-1"}})


def test_an_unknown_enumerated_value_is_an_error() -> None:
    with pytest.raises(TranslationError, match="severidad"):
        to_internal({"id": "ret-x", "severidad": "gravísima"})


def test_a_duplicate_key_is_an_error() -> None:
    with pytest.raises(TranslationError, match="duplicate"):
        read_challenge("id: ret-x\nseveridad: alta\nseveridad: media\n")


def test_mixing_a_spanish_and_an_english_name_for_the_same_field_is_an_error() -> None:
    with pytest.raises(TranslationError, match="severity"):
        to_internal({"id": "ret-x", "severidad": "alta", "severity": "high"})
