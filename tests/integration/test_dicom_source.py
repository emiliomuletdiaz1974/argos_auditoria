"""ARG-020 · DICOM connector against the simulated Orthanc PACS."""

import httpx
import pytest

from argos_connector.probes import ProbeSpec
from argos_dicom.connector import DicomConnector

from .sources import open_source_connector

pytestmark = pytest.mark.integration
ORTHANC = "http://127.0.0.1:8042"


def test_queries_studies_without_changing_the_pacs(migrated_db: str) -> None:
    before = httpx.get(f"{ORTHANC}/statistics", timeout=30).json()
    connector = open_source_connector("dev-clinical-dicom", DicomConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", "*"))
        assert scan.ok and scan.data["studies"] >= 40
        assert set(scan.data["by_modality"]) >= {"CT", "MR", "US"}
        old = connector.execute(ProbeSpec("count", "*", params={"dates": "-20100101"}))
        assert old.ok and 0 < old.data["count"] < scan.data["studies"]
        sample = connector.execute(ProbeSpec("sample", "*", params={"k": 10}))
        assert sample.ok and sample.data["n"] == 10 and "SYN" not in repr(sample)
        config = connector.execute(ProbeSpec("check_config", "pacs"))
        assert config.data["retrieve_capable"] is False
    finally:
        connector.close()
    assert httpx.get(f"{ORTHANC}/statistics", timeout=30).json() == before
