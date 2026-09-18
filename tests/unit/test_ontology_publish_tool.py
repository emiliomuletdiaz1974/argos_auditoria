"""`tools/ontology_publish.py verify` does not trust the key that travels with the bundle."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from argos_common.release import key_fingerprint

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("publish", ROOT / "tools" / "ontology_publish.py")
assert _spec is not None and _spec.loader is not None
publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish)

KEY = bytes(range(32))


class _Verified:
    version = "1.0.0"
    in_force_from = __import__("datetime").date(2026, 1, 1)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "argos-ontology-1.0.0.tar.gz"
    target.write_bytes(b"bundle")
    publish.signature_path(target).write_bytes(b"signature")
    (tmp_path / publish.PUBLIC_KEY_NAME).write_bytes(KEY)
    monkeypatch.setattr(publish, "verify_bundle", lambda *_: _Verified())
    return target


def test_the_key_beside_the_bundle_is_refused_without_a_fingerprint(bundle: Path) -> None:
    assert publish.main(["verify", str(bundle)]) == 1


def test_the_key_beside_the_bundle_is_used_when_its_fingerprint_matches(bundle: Path) -> None:
    assert publish.main(["verify", str(bundle), "--fingerprint", key_fingerprint(KEY)]) == 0
    other = key_fingerprint(bytes(32))
    assert publish.main(["verify", str(bundle), "--fingerprint", other]) == 1


def test_a_key_chosen_by_the_operator_needs_no_fingerprint(bundle: Path, tmp_path: Path) -> None:
    chosen = tmp_path / "trusted.pub"
    chosen.write_bytes(KEY)
    arguments: list[Any] = ["verify", str(bundle), "--public-key", str(chosen)]
    assert publish.main(arguments) == 0
