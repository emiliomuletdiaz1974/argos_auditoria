"""DICOM connector: C-ECHO for liveness and C-FIND for study metadata, nothing else (ARG-020)."""

import json
import re
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.association import Association

# pynetdicom generates its SOP class names at import time, so mypy cannot see them.
from pynetdicom.sop_class import (  # type: ignore[attr-defined]
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)

from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec

REQUESTED_CONTEXTS = (Verification, StudyRootQueryRetrieveInformationModelFind)
ALLOWED_ABSTRACT_SYNTAXES = frozenset(str(uid) for uid in REQUESTED_CONTEXTS)
_PENDING = (0xFF00, 0xFF01)
_DATE_RANGE = re.compile(r"^(\d{8})?-?(\d{8})?$")
_MODALITY = re.compile(r"^[A-Z]{0,4}$")


class DicomConnector(Connector):
    kind = "clinical.dicom"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ae: AE | None = None

    @property
    def ae(self) -> AE:
        if self._ae is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._ae

    @property
    def max_studies(self) -> int:
        return int(self.config.get("max_studies", 100_000))

    # ---------- lifecycle ----------
    def open(self) -> None:
        ae = AE(ae_title=str(self.config.get("ae_title", "ARGOS_QR")))
        for context in REQUESTED_CONTEXTS:
            ae.add_requested_context(context)
        timeout = float(self.config.get("timeout_s", 30))
        ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
        self._ae = ae
        # Opening talks to the PACS (association and C-ECHO): journaled and paid for (SEC-023).
        with self.follow_up(ProbeSpec("check_config", "association", params={"check": "c_echo"})):
            association = self._associate()
            try:
                status = association.send_c_echo()
            finally:
                association.release()
            if status is None or getattr(status, "Status", None) != 0x0000:
                raise ConnectionError("C-ECHO did not succeed")

    def close(self) -> None:
        self._ae = None

    def _associate(self) -> Association:
        credentials = self.context.credentials
        association = self.ae.associate(
            credentials["host"], int(credentials["port"]), ae_title=credentials["called_ae"]
        )
        if not association.is_established:
            raise ConnectionError("DICOM association was rejected, aborted or timed out")
        return association

    # ---------- rendering ----------
    def _study_query(self, spec: ProbeSpec) -> Dataset:
        dates = str(spec.params.get("dates", ""))
        modality = str(spec.params.get("modality", ""))
        if not _DATE_RANGE.match(dates):
            raise ValueError(f"invalid DICOM date range: {dates!r}")
        if not _MODALITY.match(modality):
            raise ValueError(f"invalid DICOM modality: {modality!r}")
        query = Dataset()
        query.QueryRetrieveLevel = "STUDY"
        query.StudyInstanceUID = ""
        query.StudyDate = dates
        query.ModalitiesInStudy = modality
        if spec.kind == "sample":
            query.PatientID = ""
        return query

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "check_config":
            return replace(spec, statement="LIST requested presentation contexts")
        if spec.kind not in ("scan_schema", "count", "sample"):
            return spec
        keys = {element.keyword: str(element.value) for element in self._study_query(spec)}
        return replace(spec, statement=f"C-FIND STUDY {json.dumps(keys, sort_keys=True)}")

    # ---------- probes ----------
    def _find(self, query: Dataset, cap: int) -> Iterator[Dataset]:
        association = self._associate()
        aborted = False
        found = 0
        model = StudyRootQueryRetrieveInformationModelFind
        try:
            for status, identifier in association.send_c_find(query, model):
                code = getattr(status, "Status", None)
                if code is None:
                    raise ConnectionError("C-FIND timed out or returned no status")
                if code not in (*_PENDING, 0x0000):
                    raise ConnectionError(f"C-FIND failed with status 0x{code:04X}")
                if identifier is None:
                    continue
                if found >= cap:
                    association.abort()  # never release while a C-FIND is still pending
                    aborted = True
                    return
                found += 1
                yield identifier
        finally:
            if not aborted and association.is_established:
                association.release()

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        studies = 0
        by_modality: dict[str, int] = {}
        for identifier in self._find(self._study_query(spec), self.max_studies):
            studies += 1
            for modality in str(getattr(identifier, "ModalitiesInStudy", "")).split("\\"):
                if modality:
                    by_modality[modality] = by_modality.get(modality, 0) + 1
        data = {
            "studies": studies,
            "by_modality": by_modality,
            "capped": studies >= self.max_studies,
        }
        return data, studies

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        query = self._study_query(spec)
        n = sum(1 for _ in self._find(query, self.max_studies))
        data = {
            "count": n,
            "dates": str(query.StudyDate),
            "modality": str(query.ModalitiesInStudy),
            "capped": n >= self.max_studies,
        }
        return data, n

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        limit = min(int(spec.params.get("k", 50)), self.context.budget.max_rows_per_probe)
        hasher = self.context.hasher
        studies = [
            {
                "study_uid_digest": hasher.digest(str(identifier.StudyInstanceUID)),
                "patient_id_present": bool(str(getattr(identifier, "PatientID", ""))),
                "study_year": str(getattr(identifier, "StudyDate", ""))[:4],
            }
            for identifier in self._find(self._study_query(spec), limit)
        ]
        return {"n": len(studies), "studies": studies}, len(studies)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        contexts = sorted({str(c.abstract_syntax) for c in self.ae.requested_contexts})
        capable = any(uid not in ALLOWED_ABSTRACT_SYNTAXES for uid in contexts)
        return {"requested_contexts": contexts, "retrieve_capable": capable}, len(contexts)
