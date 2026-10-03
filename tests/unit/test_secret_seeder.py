"""K-03 · the seeder of argos-core: creates what is missing, keeps what exists, shows no value."""

import base64
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SEED = Path(__file__).resolve().parents[2] / "platform" / "k8s" / "base" / "core" / "seeder"


def _seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", SEED / "seed.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Api:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.created: dict[str, dict[str, Any]] = {}

    def __call__(self, method: str, path: str, body: dict[str, Any] | None = None) -> int:
        if method == "GET":
            return 200 if path.rsplit("/", 1)[1] in self.existing else 404
        assert body is not None
        self.created[body["metadata"]["name"]] = body
        return 201


def test_it_creates_what_is_missing_and_keeps_what_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _seed()
    api = Api(existing=set())
    monkeypatch.setattr(seed, "_request", api)
    assert seed.main() == 0
    [(name, secret)] = api.created.items()
    assert name == "postgres-superuser"
    value = base64.b64decode(secret["data"]["password"]).decode()
    assert len(value) >= 40, "32 random bytes, url-safe"
    assert value not in capsys.readouterr().out, "the value is never shown"

    again = Api(existing={"postgres-superuser"})
    monkeypatch.setattr(seed, "_request", again)
    assert seed.main() == 0
    assert again.created == {}, "an existing secret is never replaced"


def test_an_answer_it_does_not_expect_stops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = _seed()
    monkeypatch.setattr(seed, "_request", lambda method, path, body=None: 403)
    assert seed.main() == 1
