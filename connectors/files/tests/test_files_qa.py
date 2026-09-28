"""QA-23 · a file count is complete, or it says it is not (quality review QA-016, 021, 025)."""

import datetime as dt
import os
from pathlib import Path
from typing import Any

import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.testing import NoBudget, make_context
from argos_files.backends import WalkIncomplete
from argos_files.backends.local import LocalBackend
from argos_files.backends.s3 import S3Backend
from argos_files.backends.smb import SmbBackend
from argos_files.connector import FilesConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"


class _SmbEntry:
    def __init__(self, name: str, directory: bool) -> None:
        self.name = name
        self._directory = directory

        class Info:
            last_write_time = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
            end_of_file = 10

        self.smb_info = Info()

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._directory

    def is_symlink(self) -> bool:
        return False


def _smb(monkeypatch: pytest.MonkeyPatch, tree: dict[str, list[_SmbEntry]]) -> SmbBackend:
    def scandir(path: str, port: int) -> list[_SmbEntry]:
        relative = path.split("\\s", 1)[1].lstrip("\\").replace("\\", "/")
        return tree.get(relative, [])

    monkeypatch.setattr("smbclient.register_session", lambda server, **kwargs: None)
    monkeypatch.setattr("smbclient.scandir", scandir)
    return SmbBackend(
        {"server": "fs", "share": "s", "username": "u", "password": "p"}, encrypt=True
    )


def _files(backend: Any, max_walk: int) -> FilesConnector:
    context = make_context(budget=NoBudget(max_rows_per_probe=10))
    connector = FilesConnector(
        SYSTEM_ID, {"protocol": "local", "max_walk_entries": max_walk}, context, backend=backend
    )
    connector.open()
    return connector


def test_smb_directories_do_not_eat_the_files_count(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = {"": [_SmbEntry(f"d{i}", True) for i in range(40)]}
    for i in range(40):
        tree[f"d{i}"] = [_SmbEntry(f"f{i}.pdf", False)]
    connector = _files(_smb(monkeypatch, tree), max_walk=100)
    data = connector.execute(ProbeSpec("count", "", params={"glob": "*"})).data
    assert data == {"count": 40, "glob": "*", "older_than_years": None, "capped": False}


def test_an_smb_walk_cut_short_says_it_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = {"": [_SmbEntry(f"d{i}", True) for i in range(40)]}
    for i in range(40):
        tree[f"d{i}"] = [_SmbEntry(f"f{i}.pdf", False)]
    connector = _files(_smb(monkeypatch, tree), max_walk=20)
    data = connector.execute(ProbeSpec("count", "", params={"glob": "*"})).data
    assert data["capped"] is True


def test_a_directory_that_cannot_be_read_makes_the_count_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "a.pdf").write_bytes(b"%PDF")
    backend = LocalBackend(tmp_path)
    original = os.walk

    def walk(top: Any, onerror: Any = None, **kwargs: Any) -> Any:
        if onerror is not None:
            onerror(PermissionError(13, "Permission denied", "/share/secret"))
        yield from original(top, onerror=onerror, **kwargs)

    monkeypatch.setattr("argos_files.backends.local.os.walk", walk)
    entries = list(backend.walk("", limit=100))
    assert any(isinstance(e, WalkIncomplete) for e in entries)
    data = _files(backend, 100).execute(ProbeSpec("count", "", params={"glob": "*"})).data
    assert data["capped"] is True and data["count"] == 1


def test_a_file_that_vanishes_during_the_walk_does_not_break_the_probe(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    backend = LocalBackend(tmp_path)
    walking = backend.walk("", limit=100)
    first = next(walking)
    assert not isinstance(first, WalkIncomplete)
    (tmp_path / "b.pdf").unlink()
    rest = list(walking)
    assert any(isinstance(e, WalkIncomplete) for e in rest)


def test_the_s3_prefix_is_a_folder_not_a_name_start() -> None:
    listed: list[str] = []

    class Paginator:
        def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:  # noqa: N803
            listed.append(Prefix)
            when = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
            return [{"Contents": [
                {"Key": "pacientes/", "Size": 0, "LastModified": when},
                {"Key": "pacientes/a.pdf", "Size": 4, "LastModified": when},
            ]}]  # fmt: skip

    class Client:
        def get_paginator(self, name: str) -> Paginator:
            return Paginator()

    backend = S3Backend.__new__(S3Backend)
    backend._client = Client()
    backend._bucket = "b"
    entries = list(backend.walk("pacientes/", limit=10))
    assert listed == ["pacientes/"], "a sibling pacientes_2019/ must not be listed"
    assert [getattr(e, "path", None) for e in entries] == ["pacientes/a.pdf"], (
        "a marker is not a file"
    )
