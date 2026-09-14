"""Listado y checksum de migraciones (sin base de datos)."""

from pathlib import Path

import pytest

from argos_comun.migraciones import checksum, listar


def test_lista_en_orden_numerico(tmp_path: Path) -> None:
    for nombre in ("0002_b.sql", "0001_a.sql", "0010_c.sql"):
        (tmp_path / nombre).write_text("SELECT 1;", encoding="utf-8")
    assert [v for v, _ in listar(tmp_path)] == [1, 2, 10]


def test_rechaza_nombres_invalidos(tmp_path: Path) -> None:
    (tmp_path / "1_sin_ceros.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="1_sin_ceros.sql"):
        listar(tmp_path)


def test_rechaza_versiones_duplicadas(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_b.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicad"):
        listar(tmp_path)


def test_checksum_cambia_con_un_byte(tmp_path: Path) -> None:
    ruta = tmp_path / "0001_a.sql"
    ruta.write_text("SELECT 1;", encoding="utf-8")
    antes = checksum(ruta)
    ruta.write_text("SELECT 1; ", encoding="utf-8")
    assert checksum(ruta) != antes
