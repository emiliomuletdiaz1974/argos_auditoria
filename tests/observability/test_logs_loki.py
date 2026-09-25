"""ARG-093 · the logs of every ARGOS service reach Loki, and say nothing they should not (F10-05).

Against the development environment, where each service pushes its own JSON lines (DP-16):

- every service of ARGOS that logs is in Loki, with the labels `service` and `level` only;
- a line that names a journal entry is found by its `journal_seq`, and the entry exists;
- the discipline of the logs: every line is JSON with the mandatory fields, carries no field that
  names a secret, and has nothing the scrubber of ARG-060 would replace.
"""

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from integration.conftest import ADMIN_DSN

from argos_common.journal_pg import PostgresJournal
from argos_connector.validators import scrub_identifiers
from argos_support.scrub import identifier_table

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
LOKI = "http://127.0.0.1:3100/loki/api/v1"
EXAMPLE = "http://127.0.0.1:8001"
# Each process names itself when it configures its logging.
SERVICES = {
    "argos-api",
    "argos-health",
    "argos-example",
    "argos-campaign-worker",
    "argos-evidence-worker",
    "argos-evidence-api",
    "argos-webhook-worker",
    "argos-ai-gateway",
}
MANDATORY = {"timestamp", "level", "service", "component", "logger", "message"}
SECRET_FIELDS = {"password", "secret", "token", "authorization", "api_key", "secret_id"}


def _get(path: str, **params: str) -> Any:
    url = f"{LOKI}{path}?{urllib.parse.urlencode(params)}" if params else f"{LOKI}{path}"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - development Loki
        return json.loads(response.read())


def _lines(query: str, since_seconds: int = 3600, limit: int = 5000) -> list[dict[str, Any]]:
    now = time.time_ns()
    answer = _get(
        "/query_range",
        query=query,
        start=str(now - since_seconds * 1_000_000_000),
        end=str(now),
        limit=str(limit),
    )
    return [
        {"labels": stream["stream"], "line": line}
        for stream in answer["data"]["result"]
        for _, line in stream["values"]
    ]


# The container of each process: a worker writes only when it starts or has work, so a service
# missing from the recent window of Loki is restarted to make it say its start line.
CONTAINERS = {
    "argos-api": "api",
    "argos-health": "health",
    "argos-example": "example",
    "argos-campaign-worker": "challenge-worker",
    "argos-evidence-worker": "evidence-worker",
    "argos-evidence-api": "evidence-api",
    "argos-webhook-worker": "webhook-worker",
    "argos-ai-gateway": "ai-gateway",
}
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "dev" / "compose.yaml")]


def _services() -> set[str]:
    return set(_get("/label/service/values").get("data", []))


def test_every_argos_service_that_logs_is_in_loki_with_two_labels() -> None:
    missing = SERVICES - _services()
    if missing:
        subprocess.run(  # noqa: S603 - fixed command against the development environment
            [*COMPOSE, "restart", *sorted(CONTAINERS[name] for name in missing)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        deadline = time.monotonic() + 120
        while SERVICES - _services() and time.monotonic() < deadline:
            time.sleep(3)
    services = _services()
    assert services >= SERVICES, sorted(SERVICES - services)
    assert set(_get("/labels").get("data", [])) <= {"service", "level", "__stream_shard__"}


def test_a_journal_entry_is_found_by_its_sequence() -> None:
    request = urllib.request.Request(f"{EXAMPLE}/demo/entries?n=1", method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        seq = int(json.loads(response.read())["last_seq"])
    query = f'{{service="argos-example"}} |= `"journal_seq": {seq}`'
    deadline = time.monotonic() + 30
    found: list[dict[str, Any]] = []
    while not found and time.monotonic() < deadline:
        found = _lines(query, since_seconds=300)
        time.sleep(1)
    assert found, f"no line with journal_seq {seq} reached Loki"
    assert json.loads(found[0]["line"])["journal_seq"] == seq
    entries = list(PostgresJournal(ADMIN_DSN).read(seq, seq))
    assert [e.seq for e in entries] == [seq]


def test_the_lines_keep_the_discipline_of_the_logs() -> None:
    lines = _lines('{service=~"argos-.+"}')
    assert lines, "no line in the last hour"
    identifiers = identifier_table()
    for item in lines:
        entry = json.loads(item["line"])
        assert set(entry) >= MANDATORY, entry
        assert not SECRET_FIELDS & {k.lower() for k in entry}, entry
        scrubbed, replaced = scrub_identifiers(item["line"], identifiers)
        assert replaced == 0, item["line"][:200]
