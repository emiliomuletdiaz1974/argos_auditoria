"""ARG-005 · migración núcleo, migrador y garantías del diario en el motor."""

import json
import shutil
from pathlib import Path
from typing import Any

import psycopg
import pytest

from argos_comun.errors import IntegridadError
from argos_comun.migraciones import aplicar

from .conftest import MIGRACIONES

pytestmark = pytest.mark.integracion

VECTORES: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "vectores" / "diario_v1.json").read_text(encoding="utf-8")
)


def test_aplica_una_vez_y_es_idempotente(bd_vacia: str) -> None:
    assert aplicar(bd_vacia, MIGRACIONES) == [1]
    assert aplicar(bd_vacia, MIGRACIONES) == []
    with psycopg.connect(bd_vacia) as c:
        assert c.execute("SELECT count(*) FROM argos.schema_version").fetchone() == (1,)
        fila = c.execute("SELECT seq, actor, action, payload FROM argos.audit_journal").fetchone()
    assert fila is not None
    assert fila[:3] == (1, "system:migrator", "schema.migrate")
    assert fila[3]["version"] == 1


def test_migracion_alterada_tras_aplicarse(bd_vacia: str, tmp_path: Path) -> None:
    copia = tmp_path / "migraciones"
    shutil.copytree(MIGRACIONES, copia)
    aplicar(bd_vacia, copia)
    with (copia / "0001_nucleo.sql").open("a", encoding="utf-8") as f:
        f.write("\n-- cambio posterior\n")
    with pytest.raises(IntegridadError, match="0001|1"):
        aplicar(bd_vacia, copia)


@pytest.mark.parametrize("v", VECTORES["asientos"], ids=lambda v: f"seq{v['seq']}")
def test_journal_hash_en_sql_reproduce_los_vectores(bd_vacia: str, v: dict[str, Any]) -> None:
    aplicar(bd_vacia, MIGRACIONES)
    with psycopg.connect(bd_vacia) as c:
        fila = c.execute(
            "SELECT argos.journal_hash(%s, %s, %s, %s, %s, %s)",
            (
                v["seq"],
                v["at_canon"],
                v["actor"],
                v["action"],
                v["payload_canon"],
                bytes.fromhex(v["prev_hash"]),
            ),
        ).fetchone()
    assert fila is not None and bytes(fila[0]).hex() == v["entry_hash"]


@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE argos.audit_journal SET actor = 'x'",
        "DELETE FROM argos.audit_journal",
        "TRUNCATE argos.audit_journal",
    ],
)
def test_el_diario_es_inmutable(bd_vacia: str, sentencia: str) -> None:
    aplicar(bd_vacia, MIGRACIONES)
    with (
        psycopg.connect(bd_vacia) as c,
        pytest.raises(psycopg.errors.RaiseException, match="inmutable"),
    ):
        c.execute(sentencia)


def test_un_rol_de_servicio_solo_escribe_por_journal_append(bd_vacia: str) -> None:
    aplicar(bd_vacia, MIGRACIONES)
    with psycopg.connect(bd_vacia, autocommit=True) as c:
        c.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'svc_prueba')"
            " THEN CREATE ROLE svc_prueba NOLOGIN; END IF; END $$"
        )
        c.execute("GRANT USAGE ON SCHEMA argos TO svc_prueba")
        c.execute("GRANT EXECUTE ON FUNCTION argos.journal_append(text, text, text) TO svc_prueba")
    with psycopg.connect(bd_vacia) as c:
        c.execute("SET ROLE svc_prueba")
        seq = c.execute("SELECT argos.journal_append('system:svc', 'prueba.ok', '{}')").fetchone()
        assert seq == (2,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "INSERT INTO argos.audit_journal VALUES "
                "(99, now(), 'x', 'x', 'x', '{}', '{}', '\\x00', '\\x00')"
            )


def test_at_canon_tiene_formato_canonico(bd_vacia: str) -> None:
    aplicar(bd_vacia, MIGRACIONES)
    with psycopg.connect(bd_vacia) as c:
        fila = c.execute("SELECT at_canon FROM argos.audit_journal WHERE seq = 1").fetchone()
    assert fila is not None
    assert len(fila[0]) == 27 and fila[0].endswith("Z") and fila[0][10] == "T"
