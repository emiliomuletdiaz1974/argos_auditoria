"""Simulated clinical sources (F02-12): HAPI FHIR R4 and a PACS that ARGOS may only query."""

import importlib.util
import io
from pathlib import Path

import httpx
import pytest
from pydicom import dcmread
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
from pynetdicom import AE
from pynetdicom.sop_class import Verification

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
FHIR = "http://127.0.0.1:8090/fhir"
ORTHANC = "http://127.0.0.1:8042"

_spec = importlib.util.spec_from_file_location("seed", ROOT / "tools" / "seed_dev_clinical.py")
assert _spec is not None and _spec.loader is not None
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def test_fhir_server_is_r4_and_seeded() -> None:
    metadata = httpx.get(f"{FHIR}/metadata", timeout=30).json()
    assert str(metadata["fhirVersion"]).startswith("4.0")
    patients = httpx.get(
        f"{FHIR}/Patient", params={"_summary": "count"}, headers=seed.NO_CACHE, timeout=30
    ).json()
    assert patients["total"] >= seed.PATIENTS


def test_orthanc_holds_synthetic_studies() -> None:
    statistics = httpx.get(f"{ORTHANC}/statistics", timeout=30).json()
    assert statistics["CountStudies"] >= seed.STUDIES


def test_argos_ae_can_echo() -> None:
    ae = AE(ae_title="ARGOS_QR")
    ae.add_requested_context(Verification)
    assoc = ae.associate("127.0.0.1", 4242, ae_title="ORTHANC")
    assert assoc.is_established
    status = assoc.send_c_echo()
    assoc.release()
    assert status is not None and status.Status == 0x0000


def test_orthanc_refuses_storage_from_argos_ae() -> None:
    # send_c_store on purpose: this proves the server refuses storage, not the connector.
    before = httpx.get(f"{ORTHANC}/statistics", timeout=30).json()
    dataset = dcmread(io.BytesIO(seed.synthetic_instance(999)))
    ae = AE(ae_title="ARGOS_QR")
    ae.add_requested_context(SecondaryCaptureImageStorage, ExplicitVRLittleEndian)
    assoc = ae.associate("127.0.0.1", 4242, ae_title="ORTHANC")
    if assoc.is_established:
        status = assoc.send_c_store(dataset)
        assoc.release()
        # pynetdicom returns an empty Dataset (no Status) when the peer answers with no status.
        assert getattr(status, "Status", None) != 0x0000
    after = httpx.get(f"{ORTHANC}/statistics", timeout=30).json()
    assert after["CountInstances"] == before["CountInstances"]
