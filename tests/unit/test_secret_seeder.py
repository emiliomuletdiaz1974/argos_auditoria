"""K-03 · the seeder of argos-core: creates what is missing, keeps what exists, shows no value.

K-06: the services live in argos-services and a pod reads secrets only of its own namespace, so a
secret marked `copy_to` is copied there with the same values: a NATS password, for instance, has to
be the same for the server and for the service that signs in with it.
"""

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
    """Secrets by namespace and name; it answers as the API of Kubernetes does."""

    def __init__(self, existing: dict[tuple[str, str], dict[str, str]] | None = None) -> None:
        self.secrets: dict[tuple[str, str], dict[str, str]] = dict(existing or {})
        self.created: list[tuple[str, str]] = []

    def __call__(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        parts = path.strip("/").split("/")  # api v1 namespaces <ns> secrets [<name>]
        namespace = parts[3]
        if method == "GET":
            found = self.secrets.get((namespace, parts[5]))
            return (200, {"data": found}) if found is not None else (404, {})
        assert body is not None
        key = (namespace, body["metadata"]["name"])
        self.secrets[key] = body["data"]
        self.created.append(key)
        return 201, {}


def test_it_creates_what_is_missing_and_keeps_what_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _seed()
    api = Api()
    monkeypatch.setattr(seed, "_request", api)
    assert seed.main() == 0
    wanted = {name for name, _, _ in seed._wanted()}
    assert {name for ns, name in api.created if ns == "argos-core"} == wanted
    shown = capsys.readouterr().out
    for data in api.secrets.values():
        for encoded in data.values():
            value = base64.b64decode(encoded).decode()
            assert len(value) >= 40, "32 random bytes, url-safe"
            assert value not in shown, "the value is never shown"

    again = Api(api.secrets)
    monkeypatch.setattr(seed, "_request", again)
    assert seed.main() == 0
    assert again.created == [], "an existing secret is never replaced"


def test_a_secret_for_the_services_is_copied_with_the_same_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _seed()
    copies = {name: targets for name, _, targets in seed._wanted() if targets}
    assert copies["nats-users"] == ["argos-services"]
    original = {"challenge": base64.b64encode(b"already-there").decode()}
    api = Api({("argos-core", "nats-users"): original})
    monkeypatch.setattr(seed, "_request", api)
    assert seed.main() == 0
    assert api.secrets[("argos-services", "nats-users")] == original
    assert ("argos-core", "nats-users") not in api.created, "the original is not touched"


def test_an_answer_it_does_not_expect_stops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = _seed()
    monkeypatch.setattr(seed, "_request", lambda method, path, body=None: (403, {}))
    assert seed.main() == 1
