"""Phase 1 acceptance test (Plan Director §8.2).

A service started with make dev writes one hundred entries; the chain verifies; an entry corrupted
on disk is detected with its position; once restored the chain is intact again.
"""

import json
import os
import urllib.request
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.integration

SERVICE_URL = os.environ.get("ARGOS_TEST_EXAMPLE_URL", "http://127.0.0.1:8001")
DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")


def _request(method: str, path: str) -> tuple[int, Any]:
    request = urllib.request.Request(SERVICE_URL + path, method=method)  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as r:  # noqa: S310
        return r.status, json.loads(r.read())


def test_running_service_is_healthy() -> None:
    status, body = _request("GET", "/health")
    assert status == 200
    assert body["checks"] == {"postgres": "ok", "journal": "ok"}


def test_one_hundred_entries_and_corruption_detected_with_position() -> None:
    status, written = _request("POST", "/demo/entries?n=100")
    assert status == 200 and written["written"] == 100
    _, verification = _request("GET", "/journal/verification")
    assert verification["intact"]
    assert verification["head_seq"] == written["last_seq"]

    target = written["last_seq"] - 50
    with psycopg.connect(DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT payload_canon FROM argos.audit_journal WHERE seq = %s", (target,)
        ).fetchone()
        assert row is not None
        original = row[0]
        conn.execute("ALTER TABLE argos.audit_journal DISABLE TRIGGER journal_no_update")
        try:
            conn.execute(
                "UPDATE argos.audit_journal SET payload_canon = %s WHERE seq = %s",
                ('{"i":-1}', target),
            )
            _, corrupted = _request("GET", "/journal/verification")
            assert not corrupted["intact"]
            assert corrupted["anomalies"][0]["seq"] == target
        finally:
            conn.execute(
                "UPDATE argos.audit_journal SET payload_canon = %s WHERE seq = %s",
                (original, target),
            )
            conn.execute("ALTER TABLE argos.audit_journal ENABLE TRIGGER journal_no_update")

    _, restored = _request("GET", "/journal/verification")
    assert restored["intact"]
