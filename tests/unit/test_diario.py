"""Pruebas unitarias del Diario Inmutable encadenado por SHA-256 (Componente ARG-005)."""

import pytest
from libs.comun.diario import (
    GENESIS_HASH,
    AsientoDiario,
    DiarioInmutable,
    VerificacionDiarioError,
)


def test_diario_genesis_and_chaining() -> None:
    diario = DiarioInmutable()
    assert diario.longitud == 0

    # 1. Registrar primer asiento (Génesis)
    asiento_1 = diario.registrar(
        componente="ARG-001",
        operacion="INICIALIZAR_SISTEMA",
        actor="proceso_arranque",
        payload_bytes=b'{"version": "0.1.0-alpha"}',
        detalles={"modulo": "nucleo"}
    )
    assert asiento_1.seq == 1
    assert asiento_1.hash_previo == GENESIS_HASH
    assert len(asiento_1.hash_actual) == 64
    assert asiento_1.es_valido() is True

    # 2. Registrar segundo asiento
    asiento_2 = diario.registrar(
        componente="ARG-011",
        operacion="CONECTAR_FUENTE",
        actor="operador_auditoria",
        payload_bytes=b'{"source_id": "db_hospital_01"}',
        detalles={"tipo": "postgresql"}
    )
    assert asiento_2.seq == 2
    assert asiento_2.hash_previo == asiento_1.hash_actual
    assert asiento_2.es_valido() is True

    # 3. Registrar tercer asiento
    asiento_3 = diario.registrar(
        componente="ARG-041",
        operacion="EJECUTAR_RETO",
        actor="motor_retos",
        payload_bytes=b'{"reto": "RGPD_SUPRESION_VERIFICADA"}',
        detalles={"resultado": "CONFORME"}
    )
    assert asiento_3.seq == 3
    assert asiento_3.hash_previo == asiento_2.hash_actual
    assert diario.longitud == 3

    # 4. Comprobar integridad de la cadena completa
    assert diario.verificar_cadena() is True


def test_diario_detecta_corrupcion_de_datos() -> None:
    diario = DiarioInmutable()
    diario.registrar("ARG-001", "OP1", "actor1", b"payload1")
    diario.registrar("ARG-001", "OP2", "actor2", b"payload2")

    # Simulamos alteración maliciosa en memoria de un metadato en el primer asiento
    diario._cadena[0].detalles["modificado_por_atacante"] = True

    # La verificación debe fallar inmediatamente
    with pytest.raises(VerificacionDiarioError) as exc_info:
        diario.verificar_cadena()

    assert "Corrupción de datos" in str(exc_info.value)


def test_diario_detecta_rotura_de_cadena_por_omision() -> None:
    diario = DiarioInmutable()
    a1 = diario.registrar("ARG-001", "OP1", "actor1", b"payload1")
    diario.registrar("ARG-001", "OP2", "actor2", b"payload2")
    a3 = diario.registrar("ARG-001", "OP3", "actor3", b"payload3")

    # Intentamos validar una lista donde se eliminó el asiento 2 para ocultar un registro
    lista_mutilada = [a1, a3]

    with pytest.raises(VerificacionDiarioError) as exc_info:
        DiarioInmutable.verificar_asientos(lista_mutilada)

    assert "Secuencia rota" in str(exc_info.value)
