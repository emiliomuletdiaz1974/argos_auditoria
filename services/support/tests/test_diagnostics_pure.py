"""ARG-088 · the diagnostic package, pure and with an inspector double (F09-11).

What the operator reviews is what leaves: every free text goes through the scrubber, secrets are
named and never shown, the index lists exactly what is there, and the encrypted package opens to
the same bytes the preview showed.
"""

import ast
import datetime as dt
import json
from pathlib import Path

import pyrage
import pytest

from argos_support import (
    DiagnosticsError,
    DiagnosticsStore,
    Preview,
    archive,
    build_package,
    collect,
    open_package,
)
from argos_support.testing import FakeInspector, service

# Synthetic identifiers that pass their validator (the same ones as the guardrails tests).
DNI = "99992001F"
IBAN = "ES9121000418450200051332"
EMAIL = "juana.sintetica@example.org"
TOKEN = "s.dev-planted-secret-4f1c9e"
DB_PASSWORD = "hunter2-planted-db"
AT = dt.datetime(2026, 9, 24, 10, 0, tzinfo=dt.UTC)
JOURNAL = [
    {"seq": 7, "actor": "user:dpo.test", "action": "campaign.approved",
     "at": "2026-09-24T09:00:00Z", "payload": {"note": f"secreto de negocio {DNI}"}},
    {"seq": 8, "actor": f"user:{DNI}", "action": "finding.transition",
     "at": "2026-09-24T09:01:00Z", "payload": {}},
]  # fmt: skip


def _inspector() -> FakeInspector:
    api = service(
        "api",
        image="argos-api:0.1.0",
        health="healthy",
        health_output=f'{{"status": "ok", "token": "{TOKEN}"}}',
        env={
            "ARGOS_VAULT_TOKEN": TOKEN,
            "ARGOS_DATABASE_URL": f"postgresql://argos:{DB_PASSWORD}@postgres:5432/argos",
            "ARGOS_LOG_LEVEL": "INFO",
        },
        mounts=("/run/secrets/approle", "/run/tls"),
    )
    worker = service("challenge-worker", image="argos-challenge-engine:0.1.0", health="starting")
    return FakeInspector(
        [api, worker],
        logs={
            "api": (
                f"GET /api/v1/inventory/nodes/{DNI} 404\n"
                f"payment to {IBAN} by {EMAIL}\n"
                f"vault token {TOKEN} and dsn postgresql://argos:{DB_PASSWORD}@postgres/argos\n"
            ),
            "challenge-worker": "worker started\n",
        },
        events=[f"2026-09-24T09:59:00Z api restart by {EMAIL}"],
    )


def _preview() -> Preview:
    return collect(_inspector(), lambda n: JOURNAL[-n:], "0.1.0", AT)


def _everything(preview: Preview) -> str:
    return "\n".join(data.decode("utf-8") for data in preview.files.values()) + (
        preview.index.decode("utf-8")
    )


def test_a_log_with_a_dni_an_iban_and_an_email_leaves_scrubbed() -> None:
    preview = _preview()
    log = preview.files["logs/api.log"].decode("utf-8")
    for value in (DNI, IBAN, EMAIL):
        assert value not in log
    assert "[DNI-1]" in log and "[IBAN-1]" in log and "[EMAIL-1]" in log
    assert log.startswith("# scrubbed: ")
    entry = {e["name"]: e for e in json.loads(preview.index)["files"]}["logs/api.log"]
    assert entry["scrubbed"] >= 3


def test_a_secret_planted_in_the_environment_appears_in_no_file() -> None:
    preview = _preview()
    text = _everything(preview)
    assert TOKEN not in text
    assert DB_PASSWORD not in text
    names = preview.files["config-names.txt"].decode("utf-8")
    assert "api ARGOS_VAULT_TOKEN" in names
    assert "api /run/secrets/approle" in names


def test_every_free_text_goes_through_the_scrubber_not_only_the_logs() -> None:
    text = _everything(_preview())
    assert DNI not in text, "journal actors, events and health outputs are scrubbed too"
    assert EMAIL not in text


def test_the_journal_tail_carries_no_payload() -> None:
    rows = json.loads(_preview().files["journal-tail.json"])
    assert [sorted(row) for row in rows] == [["action", "actor", "at", "seq"]] * 2
    assert "secreto de negocio" not in json.dumps(rows)


def test_the_index_lists_everything_and_only_what_is_there() -> None:
    preview = _preview()
    index = json.loads(preview.index)
    listed = {entry["name"]: entry for entry in index["files"]}
    assert set(listed) == set(preview.files)
    assert set(preview.files) == {
        "versions.txt", "health.json", "events.txt", "journal-tail.json", "config-names.txt",
        "logs/api.log", "logs/challenge-worker.log",
    }  # fmt: skip
    for name, data in preview.files.items():
        assert listed[name]["size"] == len(data)
        assert len(listed[name]["sha256"]) == 64
    assert "INDEX.json" not in listed
    assert "operador" in index["note"], "the note for the operator, in Spanish"
    assert index["generated_at"] == "2026-09-24T10:00:00Z"


def test_the_same_input_gives_the_same_index_and_the_same_archive() -> None:
    first, second = _preview(), _preview()
    assert first.index == second.index
    assert archive(first) == archive(second)


def test_a_package_is_only_built_for_the_index_that_was_approved() -> None:
    preview = _preview()
    recipient = str(pyrage.x25519.Identity.generate().to_public())
    with pytest.raises(DiagnosticsError, match="approved"):
        build_package(preview, "0" * 64, recipient)


def test_a_file_changed_after_the_preview_stops_the_package() -> None:
    preview = _preview()
    altered = Preview(
        {**preview.files, "events.txt": b"something else"}, preview.index, preview.generated_at
    )
    recipient = str(pyrage.x25519.Identity.generate().to_public())
    with pytest.raises(DiagnosticsError, match="index"):
        build_package(altered, preview.index_sha256, recipient)


def test_the_package_decrypts_with_the_private_key_and_matches_the_preview() -> None:
    preview = _preview()
    identity = pyrage.x25519.Identity.generate()
    package = build_package(preview, preview.index_sha256, str(identity.to_public()))
    assert TOKEN.encode() not in package and b"versions.txt" not in package, "encrypted"
    opened = open_package(package, str(identity))
    assert opened == {**preview.files, "INDEX.json": preview.index}


def test_the_store_keeps_the_preview_and_notices_a_file_edited_on_disk(tmp_path: Path) -> None:
    store = DiagnosticsStore(tmp_path)
    ident = store.request("user:admin")
    assert store.status(ident) == "collecting"
    assert store.pending() == [ident]
    store.save(ident, _preview())
    assert store.pending() == []
    assert store.status(ident) == "ready"
    assert store.load(ident).index == _preview().index
    (tmp_path / "previews" / ident / "events.txt").write_text("edited", encoding="utf-8")
    with pytest.raises(DiagnosticsError, match="index"):
        store.load(ident)


@pytest.mark.parametrize("ident", ["../x", "1727172000-ABCDEF12", "a/b", ""])
def test_the_store_refuses_an_identifier_that_is_not_its_own(tmp_path: Path, ident: str) -> None:
    store = DiagnosticsStore(tmp_path)
    with pytest.raises(DiagnosticsError):
        store.status(ident)


def test_no_collector_runs_a_command_through_the_shell() -> None:
    package = Path(__file__).resolve().parents[1] / "argos_support"
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                assert not any(k.arg == "shell" for k in node.keywords), path
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                assert name not in {"system", "popen", "getoutput", "getstatusoutput"}, path
