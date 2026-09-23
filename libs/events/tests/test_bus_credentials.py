"""The bus connects with the identity of its service: NATS decides what it may publish."""

import asyncio
from typing import Any

import pytest

from argos_events import Bus


class _Connection:
    def jetstream(self) -> Any:
        return object()


def _connect_kwargs(monkeypatch: pytest.MonkeyPatch, bus: Bus) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def connect(url: str, **kwargs: Any) -> _Connection:
        captured.update(kwargs, url=url)
        return _Connection()

    async def no_streams(js: Any) -> None:
        return None

    monkeypatch.setattr("argos_events.nats.connect", connect)
    monkeypatch.setattr("argos_events.ensure_streams", no_streams)
    asyncio.run(bus.connect())
    return captured


def test_the_service_identity_travels_in_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = Bus("inventory-ingest", "nats://nats:4222", user="inventory", password="s3cret")
    kwargs = _connect_kwargs(monkeypatch, bus)
    assert (kwargs["user"], kwargs["password"]) == ("inventory", "s3cret")
    assert kwargs["name"] == "inventory-ingest"


def test_without_credentials_nothing_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _connect_kwargs(monkeypatch, Bus("svc", "nats://nats:4222"))
    assert "user" not in kwargs and "password" not in kwargs


def test_the_password_does_not_show_in_the_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = Bus("svc", "nats://nats:4222", user="inventory", password="s3cret")
    assert "s3cret" not in repr(bus) and "s3cret" not in str(vars(bus).get("_url"))
