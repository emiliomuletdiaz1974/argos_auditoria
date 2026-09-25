"""ARG-096 · the report of the installation leaves through the airlock, signed (F10-10)."""

from pathlib import Path

import pytest

from argos_airgap.exporters import installation_exporter


def test_the_report_and_its_signature_are_written_out(tmp_path: Path) -> None:
    state, out = tmp_path / "install", tmp_path / "out"
    state.mkdir()
    out.mkdir()
    (state / "installation-report.json").write_text('{"schema": "argos/installation/1"}')
    (state / "installation-report.json.sig").write_bytes(b"signature")
    installation_exporter(state)(out, {})
    assert (out / "installation-report.json").read_text().startswith('{"schema"')
    assert (out / "installation-report.json.sig").read_bytes() == b"signature"


def test_without_a_signed_report_there_is_nothing_to_export(tmp_path: Path) -> None:
    (tmp_path / "installation-report.json").write_text("{}")
    with pytest.raises(ValueError, match="signed report"):
        installation_exporter(tmp_path)(tmp_path / "out", {})
