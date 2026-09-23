"""DICOM connector (ARG-020): query-only contexts, keyed samples, capped C-FIND, no retrieval."""

import inspect
import re
import socket
import ssl
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import (  # type: ignore[attr-defined]
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

import argos_dicom.connector as connector_module
from argos_common.errors import ConfigurationError
from argos_connector.probes import ProbeSpec
from argos_connector.testing import InMemoryJournal, assert_no_write_surface, make_context
from argos_dicom.connector import DicomConnector

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
PACS_CONTEXTS = (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Pacs:
    port: int
    queries: list[Dataset] = field(default_factory=list)


@pytest.fixture
def pacs() -> Iterator[Pacs]:
    state = Pacs(_free_port())

    def on_find(event: Any) -> Iterator[tuple[int, Dataset | None]]:
        state.queries.append(event.identifier)
        for i in range(30):
            if event.is_cancelled:
                yield (0xFE00, None)
                return
            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = f"1.2.826.0.1.3680043.2.1125.{i}"
            ds.PatientID = f"P{i:04d}"
            ds.StudyDate = f"20{i % 20:02d}0101"
            ds.ModalitiesInStudy = ("CT", "MR", "US")[i % 3]
            yield (0xFF00, ds)

    ae = AE(ae_title="PACS")
    for context in PACS_CONTEXTS:
        ae.add_supported_context(context)
    server = ae.start_server(
        ("127.0.0.1", state.port), block=False, evt_handlers=[(evt.EVT_C_FIND, on_find)]
    )
    assert server is not None  # block=False always returns the running server
    yield state
    server.shutdown()


def _connector(port: int, **config: Any) -> tuple[DicomConnector, InMemoryJournal]:
    journal = InMemoryJournal()
    credentials = {"host": "127.0.0.1", "port": str(port), "called_ae": "PACS"}
    context = make_context(credentials, journal=journal)
    # The test PACS listens without TLS: the connector accepts it only because it is declared.
    connector = DicomConnector(
        SYSTEM_ID, {"timeout_s": 5, "allow_insecure": True, **config}, context
    )
    connector.open()
    return connector, journal


def test_scan_groups_studies_by_modality(pacs: Pacs) -> None:
    connector, journal = _connector(pacs.port)
    result = connector.execute(ProbeSpec("scan_schema", "*"))
    assert result.data == {
        "studies": 30,
        "by_modality": {"CT": 10, "MR": 10, "US": 10},
        "capped": False,
    }
    assert (journal.emitted[-1].spec.statement or "").startswith("C-FIND STUDY ")


def test_count_sends_validated_keys(pacs: Pacs) -> None:
    connector, journal = _connector(pacs.port)
    params = {"dates": "-20100101", "modality": "CT"}
    result = connector.execute(ProbeSpec("count", "*", params=params))
    assert result.data["count"] == 30 and result.data["dates"] == "-20100101"
    assert pacs.queries[-1].StudyDate == "-20100101"
    assert pacs.queries[-1].ModalitiesInStudy == "CT"
    assert '"StudyDate": "-20100101"' in (journal.emitted[-1].spec.statement or "")


@pytest.mark.parametrize(("key", "value"), [("dates", "2020; DROP"), ("modality", "CT\\MR\\*")])
def test_invalid_query_keys_are_refused_before_journaling(pacs: Pacs, key: str, value: str) -> None:
    connector, journal = _connector(pacs.port)
    opened = len(journal.records)  # the association of open() is journaled on its own
    with pytest.raises(ValueError):
        connector.execute(ProbeSpec("count", "*", params={key: value}))
    assert len(journal.records) == opened


def test_sample_reveals_presence_not_identifiers(pacs: Pacs) -> None:
    connector, _ = _connector(pacs.port)
    result = connector.execute(ProbeSpec("sample", "*", params={"k": 5}))
    assert result.data["n"] == 5
    studies = result.data["studies"]
    assert all(len(s["study_uid_digest"]) == 32 and len(s["study_year"]) == 4 for s in studies)
    assert "P000" not in repr(result) and "1.2.826" not in repr(result)
    # SEC-028: the sample does not even ask for the patient; the count says whether studies exist.
    assert all("patient_id_present" not in s for s in studies)
    assert all("PatientID" not in query for query in pacs.queries)


def test_capped_find_aborts_the_association(pacs: Pacs) -> None:
    connector, _ = _connector(pacs.port, max_studies=10)
    result = connector.execute(ProbeSpec("scan_schema", "*"))
    assert result.data["studies"] == 10 and result.data["capped"] is True
    # The PACS is still usable after the abort.
    assert connector.execute(ProbeSpec("count", "*")).data["count"] == 10


def test_only_verification_and_find_are_negotiated(pacs: Pacs) -> None:
    connector, _ = _connector(pacs.port)
    result = connector.execute(ProbeSpec("check_config", "pacs"))
    expected = {str(Verification), str(StudyRootQueryRetrieveInformationModelFind)}
    assert set(result.data["requested_contexts"]) == expected
    assert result.data["retrieve_capable"] is False


def test_retrieval_and_storage_are_absent_from_the_code() -> None:
    source = inspect.getsource(connector_module)
    assert not re.search(r"send_c_(move|get|store)|InformationModel(Move|Get)|ImageStorage", source)


def test_unreachable_pacs_fails_at_open() -> None:
    credentials = {"host": "127.0.0.1", "port": str(_free_port()), "called_ae": "PACS"}
    connector = DicomConnector(
        SYSTEM_ID, {"timeout_s": 2, "allow_insecure": True}, make_context(credentials)
    )
    with pytest.raises(ConnectionError):
        connector.open()


def test_no_write_surface() -> None:
    assert_no_write_surface(DicomConnector)


def test_the_association_and_its_echo_are_journaled_and_paid(pacs: Pacs) -> None:
    """SEC-023: opening the connector talks to the PACS; that request is in the journal too."""
    connector, journal = _connector(pacs.port)
    budget: Any = connector.context.budget
    assert budget.acquired == 1
    assert [r.spec.target for r in journal.emitted] == ["association"]
    assert journal.emitted[0].outcome is not None and journal.emitted[0].outcome["ok"]


# ---------- SEC-028 · TLS on the association, unless declared ----------

CA = Path(__file__).resolve().parents[3] / "deploy" / "dev" / "sources" / "certs" / "ca.crt"


def test_a_pacs_without_tls_is_refused_unless_declared() -> None:
    credentials = {"host": "127.0.0.1", "port": str(_free_port()), "called_ae": "PACS"}
    connector = DicomConnector(SYSTEM_ID, {"timeout_s": 2}, make_context(credentials))
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        connector.open()


def test_with_its_ca_the_association_verifies_the_pacs(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Refused:
        is_established = False

    def associate(self: AE, host: str, port: int, **kwargs: Any) -> Refused:
        seen.update(kwargs)
        return Refused()

    monkeypatch.setattr(AE, "associate", associate)
    credentials = {"host": "pacs.hospital.local", "port": "11112", "called_ae": "PACS"}
    connector = DicomConnector(
        SYSTEM_ID, {"timeout_s": 2, "ca_file": str(CA)}, make_context(credentials)
    )
    with pytest.raises(ConnectionError):
        connector.open()
    context, server_name = seen["tls_args"]
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname and server_name == "pacs.hospital.local"
