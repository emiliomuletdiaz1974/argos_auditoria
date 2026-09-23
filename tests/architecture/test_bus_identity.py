"""NATS and OPA answer only to known identities (ARG-006, audit of 2026-09-18, M6 and M7).

A process that opens the bus without its user, or a container without its credentials, stops
connecting the moment the broker requires them: these tests catch it before the environment does.
"""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "dev" / "compose.yaml"
NATS_CONF = ROOT / "deploy" / "dev" / "nats" / "nats.conf"
DIRECT_BUS = re.compile(r"\bBus\(")


def _services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = yaml.safe_load(COMPOSE.read_text("utf-8"))["services"]
    return services


def _environment(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return {str(k): str(v) for k, v in env.items()}


def test_no_process_opens_the_bus_without_its_identity() -> None:
    offenders = []
    for folder in ("services", "connectors", "tools"):
        for path in (ROOT / folder).rglob("*.py"):
            if "tests" in path.parts or ".venv" in path.parts:
                continue
            if DIRECT_BUS.search(path.read_text("utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"use argos_events.bus_from_config: {offenders}"


def test_every_container_on_the_bus_has_a_known_user() -> None:
    users = set(re.findall(r"^\s*user:\s*([\w-]+)", NATS_CONF.read_text("utf-8"), re.MULTILINE))
    for name, service in _services().items():
        env = _environment(service)
        if "ARGOS_NATS_URL" not in env:
            continue
        assert env.get("ARGOS_NATS_USER") in users, f"{name}: no known NATS user"
        assert env.get("ARGOS_NATS_PASSWORD"), f"{name}: no NATS password"


def test_every_container_that_asks_opa_has_a_token() -> None:
    for name, service in _services().items():
        env = _environment(service)
        if "ARGOS_OPA_URL" in env:
            assert env.get("ARGOS_OPA_TOKEN"), f"{name}: no OPA token"
