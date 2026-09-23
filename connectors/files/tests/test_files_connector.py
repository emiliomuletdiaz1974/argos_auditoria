"""File connector (ARG-017): metadata walks, keyed samples, DICOM sniffing, confined paths."""

import os
from pathlib import Path

import pytest

from argos_common.errors import ConfigurationError, ReadOnlyViolationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import (
    InMemoryJournal,
    NoBudget,
    assert_no_write_surface,
    make_context,
)
from argos_files.backends.local import LocalBackend
from argos_files.backends.s3 import S3Backend
from argos_files.backends.smb import SmbBackend
from argos_files.connector import FilesConnector, sniff

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
NOW = 1_788_000_000.0
YEAR = 31_557_600


@pytest.fixture
def share(tmp_path: Path) -> Path:
    files = {
        "radiology/2014/SYN00000001_scan.dcm": b"\x00" * 128 + b"DICM" + b"x" * 10,
        "radiology/2014/SYN00000002_report.pdf": b"%PDF-1.4 synthetic",
        "admin/SYN00000003.docx": b"PK\x03\x04synthetic",
        "admin/notes": b"no extension",
        "admin/old/SYN00000004_report.pdf": b"%PDF-1.4 old",
    }
    for i, (name, content) in enumerate(sorted(files.items())):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        stamp = NOW - (i * 3) * YEAR
        os.utime(path, (stamp, stamp))
    return tmp_path


def _connector(share: Path, **config: object) -> tuple[FilesConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    context = make_context(journal=journal, budget=NoBudget(max_rows_per_probe=3))
    connector = FilesConnector(
        SYSTEM_ID,
        {"protocol": "local", **config},
        context,
        backend=LocalBackend(share),
        now=lambda: NOW,
    )
    connector.open()
    return connector, journal


def test_sniff_detects_dicom_before_other_signatures() -> None:
    assert sniff(b"\x00" * 128 + b"DICM") == "dicom"
    assert sniff(b"%PDF-1.7") == "pdf"
    assert sniff(b"PK\x03\x04") == "zip/ooxml"
    assert sniff(b"plain text") == "unknown"


def test_scan_aggregates_metadata_without_reading_content(share: Path) -> None:
    connector, journal = _connector(share)
    result = connector.execute(ProbeSpec("scan_schema", ""))
    assert result.data["total"] == 5 and result.data["capped"] is False
    assert result.data["by_ext"] == {"dcm": 1, "pdf": 2, "docx": 1, "(none)": 1}
    assert sum(result.data["age_years"].values()) == 5
    assert journal.emitted[0].spec.statement == "WALK / limit=1000000"


def test_scan_reports_when_the_walk_is_capped(share: Path) -> None:
    connector, _ = _connector(share, max_walk_entries=2)
    result = connector.execute(ProbeSpec("scan_schema", ""))
    assert result.data["total"] == 2
    assert result.data["capped"] is True


def test_count_by_glob_and_age(share: Path) -> None:
    connector, _ = _connector(share)
    pdfs = connector.execute(ProbeSpec("count", "", params={"glob": "*.pdf"}))
    assert pdfs.data["count"] == 2
    # The fixture ages files 3 years apart in sorted order: the two PDFs are 6 and 12 years old.
    old_pdfs = connector.execute(
        ProbeSpec("count", "", params={"glob": "*.pdf", "older_than_years": 10})
    )
    assert old_pdfs.data["count"] == 1


def test_sample_returns_types_and_keyed_digests_only(share: Path) -> None:
    connector, _ = _connector(share)
    result = connector.execute(ProbeSpec("sample", "radiology", params={"k": 50}))
    assert result.data["n"] == 2  # both files under radiology; k is also capped by the budget (3)
    assert {e["type"] for e in result.data["entries"]} == {"dicom", "pdf"}
    entries = result.data["entries"]
    assert all(len(e["path_digest"]) == 32 and len(e["head_digest"]) == 32 for e in entries)
    assert "SYN" not in repr(result)


def test_sample_is_capped_by_the_budget(share: Path) -> None:
    connector, _ = _connector(share)
    assert connector.execute(ProbeSpec("sample", "", params={"k": 50})).data["n"] == 3


@pytest.mark.parametrize("target", ["../outside", "radiology/../../outside", "..\\outside"])
def test_paths_cannot_escape_the_share_root(share: Path, target: str) -> None:
    connector, journal = _connector(share)
    with pytest.raises(ReadOnlyViolationError, match="root"):
        connector.execute(ProbeSpec("scan_schema", target))
    assert journal.emitted == [] and len(journal.rejected) == 1


def test_check_config_reports_the_visible_acl(share: Path) -> None:
    connector, _ = _connector(share)
    result = connector.execute(ProbeSpec("check_config", "admin"))
    assert result.data["target"] == "admin" and result.data["acl"]["mode"].startswith("0o")


class _ClosingBackend(LocalBackend):
    closed = False

    def close(self) -> None:
        self.closed = True


def test_close_releases_the_backend_session(share: Path) -> None:
    backend = _ClosingBackend(share)
    connector = FilesConnector(SYSTEM_ID, {"protocol": "local"}, make_context(), backend=backend)
    connector.open()
    connector.close()
    assert backend.closed is True
    with pytest.raises(RuntimeError, match="not open"):
        _ = connector.backend


def test_s3_over_clear_http_is_refused_unless_declared() -> None:
    credentials = {
        "endpoint_url": "http://s3.hospital.test",
        "access_key": "a",
        "secret_key": "s",
        "bucket": "b",
    }
    connector = FilesConnector(SYSTEM_ID, {"protocol": "s3"}, make_context(credentials))
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        connector.open()
    declared = {"protocol": "s3", "allow_insecure": True}
    allowed = FilesConnector(SYSTEM_ID, declared, make_context(credentials))
    allowed.open()
    allowed.close()


@pytest.mark.parametrize(("config", "encrypt"), [({}, True), ({"allow_insecure": True}, None)])
def test_smb_sessions_are_encrypted_unless_declared(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, object], encrypt: bool | None
) -> None:
    # Without encryption the first block of every clinical file crosses the network in clear.
    sessions: list[dict[str, object]] = []
    monkeypatch.setattr(
        "smbclient.register_session", lambda server, **kwargs: sessions.append(kwargs)
    )
    credentials = {"server": "fs01", "share": "clinical", "username": "u", "password": "p"}
    connector = FilesConnector(SYSTEM_ID, {"protocol": "smb", **config}, make_context(credentials))
    connector.open()
    assert sessions[0]["encrypt"] is encrypt


def test_unknown_protocol_is_rejected() -> None:
    connector = FilesConnector(SYSTEM_ID, {"protocol": "ftp"}, make_context())
    with pytest.raises(ValueError, match="ftp"):
        connector.open()


@pytest.mark.parametrize("cls", [FilesConnector, LocalBackend, SmbBackend, S3Backend])
def test_no_write_surface(cls: type) -> None:
    assert_no_write_surface(cls)


def test_an_smb_directory_loop_ends_within_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-053: directories count against the limit and links are not followed."""

    class Entry:
        name = "loop"

        def is_dir(self, follow_symlinks: bool = True) -> bool:
            return True

        def is_symlink(self) -> bool:
            return False

    listings: list[str] = []

    def scandir(path: str, port: int) -> list[Entry]:
        listings.append(path)
        return [Entry()]

    monkeypatch.setattr("smbclient.register_session", lambda server, **kwargs: None)
    monkeypatch.setattr("smbclient.scandir", scandir)
    backend = SmbBackend(
        {"server": "fs", "share": "s", "username": "u", "password": "p"}, encrypt=True
    )
    assert list(backend.walk("", limit=50)) == []
    assert len(listings) <= 50


def test_an_smb_link_to_a_directory_is_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Link:
        name = "elsewhere"

        def is_dir(self, follow_symlinks: bool = True) -> bool:
            return follow_symlinks  # a directory only through the link

        def is_symlink(self) -> bool:
            return True

    listings: list[str] = []

    def scandir(path: str, port: int) -> list[Link]:
        listings.append(path)
        return [Link()]

    monkeypatch.setattr("smbclient.register_session", lambda server, **kwargs: None)
    monkeypatch.setattr("smbclient.scandir", scandir)
    backend = SmbBackend(
        {"server": "fs", "share": "s", "username": "u", "password": "p"}, encrypt=True
    )
    assert list(backend.walk("", limit=50)) == []
    assert len(listings) == 1
