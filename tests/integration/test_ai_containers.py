"""ARG-052 · the AI gateway container, and the network half of the barrier (F06-13, F06-01).

The network is checked from inside the container, not by reading the YAML: a compose file can say
one thing and the running network another. From the gateway, the campaign API must not exist,
while the database —reached through its own network and with the restricted role— must.
"""

import json
import re
import subprocess
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "services" / "ai-gateway" / "Dockerfile"
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "dev" / "compose.yaml")]


def _inside(code: str) -> subprocess.CompletedProcess[str]:
    """Run Python inside the running ai-gateway container."""
    return subprocess.run(  # noqa: S603 - fixed command against the development environment
        [*COMPOSE, "exec", "-T", "ai-gateway", "/app/.venv/bin/python", "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_gateway_answers_its_health_check() -> None:
    with urllib.request.urlopen("http://127.0.0.1:8005/health", timeout=10) as response:  # noqa: S310
        assert json.loads(response.read()) == {"status": "ok", "service": "argos-ai-gateway"}


def test_the_campaign_api_does_not_exist_from_inside_the_gateway() -> None:
    """Not «refused», not «forbidden»: there is no route and no name to resolve."""
    probe = _inside(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('challenge-api', 8003), timeout=5)\n"
        "    print('REACHABLE')\n"
        "except OSError as exc:\n"
        "    print('UNREACHABLE', type(exc).__name__)\n"
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.startswith("UNREACHABLE"), probe.stdout


def test_the_database_is_reached_as_the_restricted_role() -> None:
    probe = _inside(
        "import os, psycopg\n"
        "with psycopg.connect(os.environ['ARGOS_DATABASE_URL']) as conn:\n"
        "    print(conn.execute('SELECT current_user').fetchone()[0])\n"
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "argos_ai"


def test_from_inside_the_gateway_a_verdict_cannot_be_written() -> None:
    """The permission half of the barrier, as the container sees it."""
    probe = _inside(
        "import os, psycopg\n"
        "try:\n"
        "    with psycopg.connect(os.environ['ARGOS_DATABASE_URL']) as conn:\n"
        "        conn.execute(\"UPDATE argos.verdicts SET result = 'compliant'\")\n"
        "    print('WROTE')\n"
        "except psycopg.errors.InsufficientPrivilege:\n"
        "    print('DENIED')\n"
    )
    assert probe.stdout.strip() == "DENIED", probe.stdout + probe.stderr


def test_the_image_does_not_run_as_root_and_carries_no_secrets_nor_weights() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}
    assert not re.search(r"^(ENV|ARG)\s+\S*(TOKEN|PASSWORD|SECRET|KEY)", text, re.MULTILINE)
    assert not re.search(r"\.(gguf|safetensors|bin|pt)\b", text), "weights never go in the image"
