"""Seed the simulated clinical sources (HAPI FHIR and Orthanc) with synthetic data. Idempotent.

Every identifier is SYN-prefixed and every name is "Synthetic": no real person.

Usage: uv run python tools/seed_dev_clinical.py
"""

import base64
import io
import time
import uuid
from typing import Any

import httpx
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

FHIR = "http://127.0.0.1:8090/fhir"
ORTHANC = "http://127.0.0.1:8042"
PATIENTS = 200
STUDIES = 40
CONSENT_SCOPE = "http://terminology.hl7.org/CodeSystem/consentscope"
NO_CACHE = {"Cache-Control": "no-cache"}


def wait_for(url: str, timeout_s: float = 300.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    raise TimeoutError(f"{url} did not become ready in {timeout_s:.0f}s")


def _patient(i: int) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "identifier": [{"system": "urn:argos:synthetic", "value": f"SYN{i:08d}"}],
        "name": [{"family": f"Person{i}", "given": ["Synthetic"]}],
        "gender": ("female", "male", "other")[i % 3],
        "birthDate": f"{1940 + i % 60}-01-01",
    }


def _post(resource: dict[str, Any], full_url: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "resource": resource,
        "request": {"method": "POST", "url": resource["resourceType"]},
    }
    if full_url is not None:
        entry["fullUrl"] = full_url
    return entry


def fhir_bundle() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for i in range(PATIENTS):
        ref = f"urn:uuid:{uuid.UUID(int=i + 1)}"
        subject = {"reference": ref}
        entries.append(_post(_patient(i), ref))
        for j in range(2):
            observation = {
                "resourceType": "Observation",
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                "subject": subject,
                "valueQuantity": {"value": 60 + (i + j) % 40, "unit": "beats/min"},
            }
            entries.append(_post(observation))
        if i % 2 == 0:
            condition = {
                "resourceType": "Condition",
                "subject": subject,
                "code": {"text": "Synthetic condition"},
            }
            entries.append(_post(condition))
        if i % 4 == 0:
            consent = {
                "resourceType": "Consent",
                "status": "active" if i % 8 else "inactive",
                "scope": {"coding": [{"system": CONSENT_SCOPE, "code": "patient-privacy"}]},
                "category": [{"coding": [{"system": "http://loinc.org", "code": "59284-0"}]}],
                "patient": subject,
            }
            entries.append(_post(consent))
        if i % 10 == 0:
            note = base64.b64encode(b"synthetic clinical note").decode("ascii")
            document = {
                "resourceType": "DocumentReference",
                "status": "current",
                "subject": subject,
                "content": [{"attachment": {"contentType": "text/plain", "data": note}}],
            }
            entries.append(_post(document))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def synthetic_instance(i: int) -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("synthetic.dcm", {}, file_meta=meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientID = f"SYN{i % 25:08d}"
    ds.PatientName = f"Synthetic^Person{i % 25}"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyDate = f"{2003 + i % 22}{1 + i % 9:02d}15"
    ds.Modality = ("CT", "MR", "US")[i % 3]
    ds.Rows = ds.Columns = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(64)
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def main() -> int:
    wait_for(f"{FHIR}/metadata")
    wait_for(f"{ORTHANC}/system")
    with httpx.Client(timeout=120) as client:
        # HAPI caches search results for a minute: without no-cache a stale zero would re-seed.
        count = client.get(f"{FHIR}/Patient", params={"_summary": "count"}, headers=NO_CACHE).json()
        if int(count.get("total", 0)) < PATIENTS:
            client.post(FHIR, json=fhir_bundle()).raise_for_status()
        studies = int(client.get(f"{ORTHANC}/statistics").json()["CountStudies"])
        for i in range(studies, STUDIES):
            client.post(
                f"{ORTHANC}/instances",
                content=synthetic_instance(i),
                headers={"Content-Type": "application/dicom"},
            ).raise_for_status()
    print("development clinical sources seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
