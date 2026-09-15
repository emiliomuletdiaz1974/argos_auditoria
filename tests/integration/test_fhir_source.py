"""ARG-020 · FHIR connector against the simulated HAPI FHIR R4 server."""

import httpx
import pytest

from argos_connector.probes import ProbeSpec
from argos_connector.testing import assert_http_writes_rejected
from argos_fhir.connector import FhirConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration
FHIR = "http://127.0.0.1:8090/fhir"
# HAPI reuses a search result for about a minute: a cached total would make "before" equal
# "after" by construction and the zero-writes check would prove nothing.
NO_CACHE = {"Cache-Control": "no-cache"}


def _history_total() -> int:
    response = httpx.get(
        f"{FHIR}/_history", params={"_summary": "count"}, headers=NO_CACHE, timeout=30
    )
    return int(response.json()["total"])


def test_counts_and_samples_without_changing_the_server(migrated_db: str) -> None:
    history = _history_total()
    connector = open_source_connector("dev-clinical-fhir", FhirConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", "*"))
        sensitive = set(scan.data["sensitive_present"])
        assert {"Patient", "Observation", "Condition", "Consent"} <= sensitive
        assert connector.execute(ProbeSpec("count", "/Patient")).data["count"] >= 200
        assert connector.execute(ProbeSpec("count", "/Observation")).data["count"] >= 400
        params = {"fields": ["resource.gender"], "k": 10}
        sample = connector.execute(ProbeSpec("sample", "/Patient", params=params))
        assert sample.ok and sample.data["n"] == 10
        request = connector._request
        assert_http_writes_rejected(lambda method, path: request(method, path), "/Patient")
    finally:
        connector.close()
    assert _history_total() == history
