"""ARG-019 · REST connector against the public endpoints of the development Keycloak."""

from collections.abc import Iterator

import pytest

from argos_common.errors import ReadOnlyViolationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import assert_http_writes_rejected
from argos_rest.connector import RestConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration
CERTS = "/realms/argos/protocol/openid-connect/certs"


@pytest.fixture
def connector(migrated_db: str) -> Iterator[RestConnector]:
    c = open_source_connector("dev-api-keycloak", RestConnector, migrated_db)
    yield c
    c.close()


def test_scan_count_sample_and_headers(connector: RestConnector) -> None:
    scan = connector.execute(ProbeSpec("scan_schema", "*"))
    assert scan.ok and all(r["status"] < 500 for r in scan.data["routes"])
    keys = connector.execute(ProbeSpec("count", CERTS))
    assert keys.ok and keys.data["count"] >= 1
    sample_spec = ProbeSpec("sample", CERTS, params={"fields": ["kid", "alg"], "k": 5})
    sample = connector.execute(sample_spec)
    assert sample.ok and sample.data["n"] >= 1
    headers = connector.execute(ProbeSpec("check_config", "/realms/argos"))
    assert headers.ok and headers.data["status"] == 200


def test_writes_and_admin_paths_are_rejected(connector: RestConnector) -> None:
    assert_http_writes_rejected(lambda method, path: connector._request(method, path), CERTS)
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("count", "/admin/realms"))
