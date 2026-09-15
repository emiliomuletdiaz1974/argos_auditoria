"""Keyed pseudonymisation of sampled values and connector credentials (ARG-011, ARG-009)."""

import pytest

from argos_common.errors import SecretNotAccessibleError
from argos_connector.credentials import load_credentials
from argos_connector.minimize import ValueHasher

KEY = bytes(range(32))


def test_digest_is_deterministic_and_keyed() -> None:
    a, b = ValueHasher(KEY), ValueHasher(bytes(reversed(range(32))))
    assert a.digest("12345678Z") == a.digest("12345678Z")
    assert a.digest("12345678Z") != b.digest("12345678Z")
    assert len(a.digest("x")) == 32


def test_none_and_empty_string_do_not_collide() -> None:
    hasher = ValueHasher(KEY)
    assert hasher.digest(None) != hasher.digest("")


def test_bytes_and_numbers_are_accepted() -> None:
    hasher = ValueHasher(KEY)
    assert hasher.digest(b"abc") == hasher.digest("abc")
    assert hasher.digest(42) == hasher.digest("42")


def test_short_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        ValueHasher(b"short")


def test_from_hex() -> None:
    assert ValueHasher.from_hex(KEY.hex()).digest("a") == ValueHasher(KEY).digest("a")


class FakeStore:
    def __init__(self, data: dict[str, dict[str, str]]) -> None:
        self.data = data
        self.paths: list[str] = []

    def read(self, path: str) -> dict[str, str]:
        self.paths.append(path)
        if path not in self.data:
            raise SecretNotAccessibleError("secret not accessible", details={"path": path})
        return dict(self.data[path])


def test_credentials_are_read_from_the_connector_branch() -> None:
    system_id = "0190f000-0000-7000-8000-000000000001"
    store = FakeStore({f"connectors/{system_id}": {"url": "postgresql://ro@db/x"}})
    assert load_credentials(store, system_id) == {"url": "postgresql://ro@db/x"}
    assert store.paths == [f"connectors/{system_id}"]


def test_credentials_need_a_uuid_system_id() -> None:
    with pytest.raises(ValueError):
        load_credentials(FakeStore({}), "../services/api/db")
