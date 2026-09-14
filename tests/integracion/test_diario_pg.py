"""Diario v1 contra PostgreSQL: prueba de la Fase 1 y concurrencia (ADR-0002)."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from argos_comun.diario import GENESIS
from argos_comun.diario_pg import DiarioPostgres

pytestmark = pytest.mark.integracion


def test_cien_asientos_integros(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    base, _ = diario.cabeza()  # la migración ya escribió su asiento
    for i in range(100):
        diario.registrar("system:prueba", "prueba.escribir", {"i": i})
    r = diario.verificar()
    assert r.integro
    assert r.verificados == base + 100
    assert diario.cabeza()[0] == base + 100


def test_corrupcion_en_disco_senala_la_posicion(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    for i in range(50):
        diario.registrar("system:prueba", "prueba.escribir", {"i": i})
    with psycopg.connect(bd_migrada, autocommit=True) as c:  # un DBA malicioso salta el trigger
        c.execute("ALTER TABLE argos.audit_journal DISABLE TRIGGER journal_no_update")
        c.execute("UPDATE argos.audit_journal SET payload_canon = '{\"i\":999}' WHERE seq = 37")
        c.execute("ALTER TABLE argos.audit_journal ENABLE TRIGGER journal_no_update")
    r = diario.verificar()
    assert not r.integro
    assert r.anomalias[0].seq == 37


def test_escrituras_concurrentes_no_bifurcan_la_cadena(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    base, _ = diario.cabeza()

    def escribir(hilo: int) -> None:
        for i in range(25):
            diario.registrar(f"system:hilo{hilo}", "prueba.concurrencia", {"i": i})

    with ThreadPoolExecutor(max_workers=8) as ejecutor:
        list(ejecutor.map(escribir, range(8)))
    r = diario.verificar()
    assert r.integro, r.anomalias[:3]
    assert r.cabeza_seq == base + 200


def test_rollback_del_llamador_no_deja_huecos(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    base, _ = diario.cabeza()
    with psycopg.connect(bd_migrada) as conn:
        diario.registrar("system:prueba", "prueba.rollback", {"x": 1}, conn=conn)
        conn.rollback()
    seq = diario.registrar("system:prueba", "prueba.tras_rollback", {"x": 2})
    assert seq == base + 1
    assert diario.verificar().integro


def test_verificacion_por_rango(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    for i in range(20):
        diario.registrar("system:prueba", "prueba.rango", {"i": i})
    r = diario.verificar(desde=10, hasta=15)
    assert r.integro and r.verificados == 6 and r.cabeza_seq == 15


def test_cabeza_de_diario_vacio(bd_vacia: str) -> None:
    with psycopg.connect(bd_vacia, autocommit=True) as c:
        c.execute("CREATE SCHEMA argos")
        c.execute(
            "CREATE TABLE argos.audit_journal (seq bigint, at_canon text, actor text, action text,"
            " payload_canon text, prev_hash bytea, entry_hash bytea)"
        )
    assert DiarioPostgres(bd_vacia).cabeza() == (0, GENESIS)


def test_payload_con_flotante_no_llega_a_la_base(bd_migrada: str) -> None:
    diario = DiarioPostgres(bd_migrada)
    base, _ = diario.cabeza()
    with pytest.raises(ValueError):
        diario.registrar("system:prueba", "prueba.float", {"x": 1.5})
    assert diario.cabeza()[0] == base
