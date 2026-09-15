"""CloudEvents envelope and declared streams (ARG-006)."""

import uuid

import pytest

from argos_events import STREAMS, envelope


def test_cloudevents_envelope() -> None:
    e = envelope("inventory", "discovery.table_found.v1", {"table": "appointments"})
    assert e["specversion"] == "1.0"
    assert e["source"] == "//argos/inventory"
    assert e["type"] == "eu.argos.discovery.table_found.v1"
    assert e["datacontenttype"] == "application/json"
    assert e["data"] == {"table": "appointments"}
    assert uuid.UUID(e["id"]).version == 7


@pytest.mark.parametrize("event_type", ["table", "discovery.table_found", "Discovery.x.v1"])
def test_invalid_event_type(event_type: str) -> None:
    with pytest.raises(ValueError):
        envelope("svc", event_type, {})


def test_streams_match_the_phase_document() -> None:
    by_name = {s.name: s for s in STREAMS}
    assert by_name["DISCOVERY"].subjects == ["argos.discovery.>"]
    assert by_name["CHALLENGE"].subjects == ["argos.challenge.>", "argos.campaign.>"]
    assert by_name["EVIDENCE"].subjects == ["argos.evidence.>"]
    assert by_name["DISCOVERY"].max_age == 30 * 86400
    assert by_name["CHALLENGE"].max_age == 90 * 86400
    assert by_name["EVIDENCE"].max_bytes == 50 * 1024**3
