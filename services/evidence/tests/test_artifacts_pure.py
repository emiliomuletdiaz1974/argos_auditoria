"""ARG-062 · the artifact: canonical bytes, its own excluded hash and nothing personal in it."""

import asyncio
import datetime as dt
import hashlib
import json
from typing import Any

import pytest

from argos_evidence.artifacts import (
    SCHEMA,
    ArtifactNotMinimisedError,
    ArtifactRecord,
    announce_artifact,
    artifact_key,
    build_artifact,
    personal_identifiers,
    verify_artifact,
)

CAMPAIGN = "0199a000-0000-7000-8000-000000000001"
VERDICT = "0199a000-0000-7000-8000-000000000002"


def _row(detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": VERDICT,
        "campaign_id": CAMPAIGN,
        "unit_id": "u" * 64,
        "challenge_id": "sec-tls-in-transit",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": "0199a000-0000-7000-8000-000000000003",
        "node_key": "k" * 64,
        "result": "non_compliant",
        "verdict": {
            "via": "threshold",
            "detail": detail if detail is not None else {"field": "rows.0.ssl", "observed": "off"},
        },
        "verdict_hash": "a" * 64,
        "probe_journal_seq": 42,
        "created_at": dt.datetime(2026, 9, 18, 9, 30, 1, 250000, tzinfo=dt.UTC),
    }


def test_the_same_verdict_always_gives_the_same_bytes() -> None:
    assert build_artifact(_row()) == build_artifact(_row())
    shifted = _row()
    shifted["created_at"] = shifted["created_at"].astimezone(dt.timezone(dt.timedelta(hours=2)))
    assert build_artifact(shifted) == build_artifact(_row())


def test_the_bytes_are_the_journal_canonical_form() -> None:
    body = build_artifact(_row())
    document = json.loads(body)
    assert body == json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def test_the_artifact_answers_the_expert_questions_on_its_own() -> None:
    document = json.loads(build_artifact(_row()))
    assert document["schema"] == SCHEMA
    assert document["campaign_id"] == CAMPAIGN
    assert document["verdict_id"] == VERDICT
    assert document["challenge"] == {"id": "sec-tls-in-transit", "version": "1.0"}
    assert document["obligation"] == "OBL-RGPD-32-3"
    assert document["result"] == "non_compliant"
    assert document["query_journal_seq"] == 42
    assert document["evaluated_at"] == "2026-09-18T09:30:01.250000Z"
    assert document["verdict_hash"] == "a" * 64


def test_the_self_excluded_hash_verifies_and_catches_any_change() -> None:
    body = build_artifact(_row())
    assert verify_artifact(body)
    document = json.loads(body)
    unsigned = {k: v for k, v in document.items() if k != "sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert document["sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    tampered = body.replace(b"non_compliant", b"compliant_xx")
    assert not verify_artifact(tampered)
    assert not verify_artifact(body + b" ")
    assert not verify_artifact(b"not json")


def test_a_validated_identifier_in_the_detail_is_found() -> None:
    document = {
        "detail": {"sample": ["ok", "Paciente 12345678Z"], "iban": "ES9121000418450200051332"}
    }
    assert sorted(personal_identifiers(document)) == ["$.detail.iban", "$.detail.sample[1]"]


def test_identifiers_of_the_platform_are_not_personal() -> None:
    document = json.loads(build_artifact(_row({"rows": 12, "tables": ["patients"]})))
    assert personal_identifiers(document) == []


def test_an_artifact_that_would_carry_an_identifier_is_refused() -> None:
    with pytest.raises(ArtifactNotMinimisedError, match=r"\$\.detail\.observed"):
        build_artifact(_row({"observed": "X1234567L"}))


def test_the_key_is_the_documented_one() -> None:
    assert artifact_key(CAMPAIGN, VERDICT) == f"campaigns/{CAMPAIGN}/artifacts/{VERDICT}.json"


def test_the_pointer_is_announced_on_the_evidence_stream() -> None:
    class Bus:
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def publish(self, subject: str, event_type: str, data: dict[str, Any]) -> int:
            self.events.append((subject, event_type, data))
            return 1

    bus = Bus()
    record = ArtifactRecord(CAMPAIGN, VERDICT, artifact_key(CAMPAIGN, VERDICT), "v1", "b" * 64)
    asyncio.run(announce_artifact(bus, record))
    subject, event_type, data = bus.events[0]
    assert subject == "argos.evidence.artifact_written"
    assert event_type == "evidence.artifact_written.v1"
    assert data == {
        "campaign_id": CAMPAIGN,
        "verdict_id": VERDICT,
        "key": record.key,
        "version_id": "v1",
        "sha256": "b" * 64,
    }
