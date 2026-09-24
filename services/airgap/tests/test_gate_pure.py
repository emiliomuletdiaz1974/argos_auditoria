"""ARG-090 · the airlock, pure: what may come in, what may go out, and what is written down.

One formal door for the appliance without network. What comes in is verified by its own importer
(the same verification as through any other path) before anything is applied; what goes out is a
closed list of kinds, a constant and not configuration. Every file, accepted or not, is recorded
with its SHA-256.
"""

import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import argos_updater
from argos_airgap import EXPORT_KINDS, IMPORT_RULES, Gate, check_name, importers
from argos_airgap.importers import tsr_importer, tsr_name, update_importer
from argos_evidence.core.timestamp import TimestampRejectedError
from argos_updater.testing import public_key, signed_bundle

KEY = Ed25519PrivateKey.generate()
OBJECT = "campaigns/0192b000-0000-7000-8000-000000000001/root.sig"


class Journal:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any], str]] = []

    def __call__(self, actor: str, action: str, detail: dict[str, Any], outcome: str) -> None:
        self.entries.append((actor, action, detail, outcome))


def _gate(tmp_path: Path, importers_: dict[str, Any] | None = None, **exporters: Any) -> Gate:
    for folder in ("in", "out", "work"):
        (tmp_path / folder).mkdir(exist_ok=True)
    return Gate(
        tmp_path / "in",
        tmp_path / "out",
        tmp_path / "work",
        importers=importers_ or {},
        exporters=exporters,
        record=Journal(),
    )


def _tar(folder: Path, into: Path) -> None:
    with tarfile.open(into, "w") as tar:
        for path in sorted(folder.rglob("*")):
            tar.add(path, arcname=path.relative_to(folder).as_posix(), recursive=False)


def test_the_list_of_exports_is_a_closed_constant() -> None:
    assert frozenset({"tsq", "diagnostics", "dossier", "credential"}) == EXPORT_KINDS
    assert isinstance(EXPORT_KINDS, frozenset)


def test_an_export_outside_the_list_is_refused_and_written_down(tmp_path: Path) -> None:
    gate = _gate(tmp_path, tsq=lambda folder, params: None)
    with pytest.raises(PermissionError, match="database"):
        gate.export("database", "user:admin", {})
    assert list((tmp_path / "out").iterdir()) == []
    [(actor, action, detail, outcome)] = gate.record.entries  # type: ignore[attr-defined]
    assert (actor, action, outcome) == ("user:admin", "airgap.export", "refused")
    assert detail["kind"] == "database"


def test_a_gate_cannot_be_given_an_exporter_outside_the_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="closed list"):
        _gate(tmp_path, database=lambda folder, params: None)


def test_an_export_writes_its_files_with_their_hashes(tmp_path: Path) -> None:
    def tsq(folder: Path, params: dict[str, str]) -> None:
        (folder / "a.tsq").write_bytes(b"query")

    gate = _gate(tmp_path, tsq=tsq)
    exported = gate.export("tsq", "user:admin", {})
    assert [f["name"] for f in exported.files] == ["a.tsq"]
    assert (tmp_path / "out" / exported.id / "a.tsq").read_bytes() == b"query"
    [(_, action, detail, outcome)] = gate.record.entries  # type: ignore[attr-defined]
    assert (action, outcome) == ("airgap.export", "succeeded")
    assert detail["files"] == 1 and len(detail["sha256"]) == 64


@pytest.mark.parametrize(
    "name",
    ["../argos-update-1.0.tar", "..\\argos-update-1.0.tar", "a/b.tsr", ".hidden.tsr", "x.exe", ""],
)
def test_a_name_outside_the_patterns_is_refused(name: str) -> None:
    assert check_name(name) is None


def test_the_patterns_recognise_each_kind() -> None:
    assert check_name("argos-update-0.2.0.tar") == "update"
    assert check_name("argos-ontology-1.4.0.tar.gz") == "content"
    assert check_name(tsr_name(OBJECT)) == "tsr"


def test_a_symbolic_link_is_refused_without_reading_it(tmp_path: Path) -> None:
    gate = _gate(tmp_path, {"tsr": lambda path, actor: "applied"})
    secret = tmp_path / "secret.txt"
    secret.write_text("never read", encoding="utf-8")
    try:
        os.symlink(secret, tmp_path / "in" / tsr_name(OBJECT))
    except OSError:
        pytest.skip("this system does not let the tests create symbolic links")
    [result] = gate.scan("user:admin")
    assert result.result == "rejected" and "regular file" in result.reason
    assert result.sha256 is None, "not read"
    assert list((tmp_path / "work").iterdir()) == []


def test_a_folder_or_an_unknown_file_is_refused(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    (tmp_path / "in" / "argos-update-0.2.0.tar").mkdir()
    (tmp_path / "in" / "notes.txt").write_text("hola", encoding="utf-8")
    results = {r.file: r for r in gate.scan("user:admin")}
    assert results["argos-update-0.2.0.tar"].reason.startswith("not a regular file")
    assert results["notes.txt"].reason == "not a kind the airlock imports"
    assert len(gate.record.entries) == 2  # type: ignore[attr-defined]


def test_a_file_larger_than_its_kind_allows_is_refused(tmp_path: Path) -> None:
    gate = _gate(tmp_path, {"tsr": lambda path, actor: "applied"})
    big = IMPORT_RULES["tsr"].max_bytes + 1
    (tmp_path / "in" / tsr_name(OBJECT)).write_bytes(b"\0" * big)
    [result] = gate.scan("user:admin")
    assert result.result == "rejected" and "larger" in result.reason


def test_a_reply_with_an_invalid_signature_is_rejected_and_not_applied(tmp_path: Path) -> None:
    applied: list[str] = []

    def accept(object_key: str, reply: bytes) -> None:
        raise TimestampRejectedError("the reply does not chain to a trusted root")

    gate = _gate(tmp_path, {"tsr": tsr_importer(lambda: [OBJECT], accept)})
    (tmp_path / "in" / tsr_name(OBJECT)).write_bytes(b"forged reply")
    [result] = gate.scan("user:admin")
    assert result.result == "rejected"
    assert "trusted root" in result.reason
    assert applied == []
    [(_, action, detail, outcome)] = gate.record.entries  # type: ignore[attr-defined]
    assert (action, outcome) == ("airgap.import", "refused")
    assert detail["sha256"] and detail["kind"] == "tsr"


def test_a_reply_for_nothing_queued_is_rejected(tmp_path: Path) -> None:
    gate = _gate(tmp_path, {"tsr": tsr_importer(lambda: [], lambda key, reply: None)})
    (tmp_path / "in" / tsr_name(OBJECT)).write_bytes(b"reply")
    [result] = gate.scan("user:admin")
    assert result.result == "rejected" and "queued" in result.reason


def _updates(tmp_path: Path) -> tuple[Any, Path, Path]:
    inbox, queue = tmp_path / "update" / "inbox", tmp_path / "update" / "queue"
    inbox.mkdir(parents=True)
    importer = update_importer(inbox, queue, lambda: "0.1.0", public_key(KEY))
    return importer, inbox, queue


def test_an_update_without_signature_is_rejected_by_the_verification_of_the_updater(
    tmp_path: Path,
) -> None:
    assert importers.verify_bundle is argos_updater.verify_bundle, "the same check, not another"
    bundle = signed_bundle(tmp_path / "made", "0.2.0", KEY, ["argos-example"])
    (bundle / argos_updater.SIGNATURE).unlink()
    importer, inbox, queue = _updates(tmp_path)
    gate = _gate(tmp_path, {"update": importer})
    _tar(bundle, tmp_path / "in" / "argos-update-0.2.0.tar")
    [result] = gate.scan("user:admin")
    assert result.result == "rejected"
    assert "signed manifest" in result.reason
    assert list(inbox.iterdir()) == [] and not queue.exists()


def test_a_signed_update_is_verified_and_queued_for_the_updater(tmp_path: Path) -> None:
    bundle = signed_bundle(tmp_path / "made", "0.2.0", KEY, ["argos-example"])
    importer, inbox, queue = _updates(tmp_path)
    gate = _gate(tmp_path, {"update": importer})
    _tar(bundle, tmp_path / "in" / "argos-update-0.2.0.tar")
    [result] = gate.scan("user:admin")
    assert result.result == "imported", result.reason
    assert (inbox / "bundle-0.2.0" / argos_updater.MANIFEST).is_file()
    [request] = list(queue.glob("*.json"))
    assert json.loads(request.read_text(encoding="utf-8"))["bundle"] == "bundle-0.2.0"


def test_an_update_archive_that_escapes_its_folder_is_rejected(tmp_path: Path) -> None:
    importer, inbox, _ = _updates(tmp_path)
    gate = _gate(tmp_path, {"update": importer})
    with tarfile.open(tmp_path / "in" / "argos-update-0.2.0.tar", "w") as tar:
        data = b"x"
        info = tarfile.TarInfo("../../escaped.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    [result] = gate.scan("user:admin")
    assert result.result == "rejected"
    assert not (tmp_path / "escaped.txt").exists()
    assert list(inbox.iterdir()) == []


def test_the_work_zone_is_empty_after_every_import(tmp_path: Path) -> None:
    gate = _gate(tmp_path, {"tsr": tsr_importer(lambda: [OBJECT], lambda key, reply: None)})
    (tmp_path / "in" / tsr_name(OBJECT)).write_bytes(b"reply")
    [result] = gate.scan("user:admin")
    assert result.result == "imported"
    assert list((tmp_path / "work").iterdir()) == []
    assert (tmp_path / "in" / tsr_name(OBJECT)).exists(), "the medium is read-only: never moved"
