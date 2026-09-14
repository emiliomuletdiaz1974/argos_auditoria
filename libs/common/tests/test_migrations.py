"""Migration listing and checksum (no database)."""

from pathlib import Path

import pytest

from argos_common.migrations import checksum, list_migrations


def test_lists_in_numeric_order(tmp_path: Path) -> None:
    for name in ("0002_b.sql", "0001_a.sql", "0010_c.sql"):
        (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    assert [v for v, _ in list_migrations(tmp_path)] == [1, 2, 10]


def test_rejects_invalid_names(tmp_path: Path) -> None:
    (tmp_path / "1_no_padding.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="1_no_padding.sql"):
        list_migrations(tmp_path)


def test_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_b.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        list_migrations(tmp_path)


def test_checksum_changes_with_one_byte(tmp_path: Path) -> None:
    path = tmp_path / "0001_a.sql"
    path.write_text("SELECT 1;", encoding="utf-8")
    before = checksum(path)
    path.write_text("SELECT 1; ", encoding="utf-8")
    assert checksum(path) != before
