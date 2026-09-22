"""ARG-079 · the signature a receiver can check, and the templates that are configuration.

The receiver side is written here by hand, from what the documentation tells a client to do,
without importing ours: if the two ever disagree, a real ITSM would reject ARGOS.
"""

import hashlib
import hmac
import json

import pytest

from argos_api.webhooks.signing import SIGNATURE_HEADER, TOLERANCE_SECONDS, sign, verify
from argos_api.webhooks.templates import TEMPLATES_FILE, TemplateError, load_templates, render

SECRET = "a-secret-the-client-chose"
BODY = b'{"type":"finding_opened","severity":"critical"}'
EVENT = {
    "type": "finding_opened",
    "finding_id": "f-1",
    "challenge_id": "sec-encryption-at-rest",
    "severity": "critical",
}


def _receiver_accepts(secret: str, header: str, body: bytes, now: int) -> bool:
    """What the documentation tells a receiver to do, step by step."""
    parts = dict(item.split("=", 1) for item in header.split(","))
    timestamp, received = parts["t"], parts["v1"]
    if abs(now - int(timestamp)) > 300:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), received)


def test_a_receiver_verifies_the_signature_with_what_is_documented() -> None:
    header = sign(SECRET, 1_760_000_000, BODY)
    assert SIGNATURE_HEADER == "X-Argos-Signature"
    assert _receiver_accepts(SECRET, header, BODY, now=1_760_000_010)
    assert verify(SECRET, header, BODY, now=1_760_000_010)


def test_a_changed_body_or_another_secret_does_not_verify() -> None:
    header = sign(SECRET, 1_760_000_000, BODY)
    assert not verify(SECRET, header, BODY.replace(b"critical", b"low"), now=1_760_000_000)
    assert not verify("another-secret", header, BODY, now=1_760_000_000)
    assert not _receiver_accepts("another-secret", header, BODY, now=1_760_000_000)


def test_an_old_signature_is_a_replay_and_is_refused() -> None:
    header = sign(SECRET, 1_760_000_000, BODY)
    late = 1_760_000_000 + TOLERANCE_SECONDS + 1
    assert not verify(SECRET, header, BODY, now=late)
    assert not _receiver_accepts(SECRET, header, BODY, now=late)


def test_a_malformed_header_does_not_verify() -> None:
    for header in ("", "v1=abc", "t=1,v1=", "t=x,v1=abc", "garbage"):
        assert not verify(SECRET, header, BODY, now=1)


def test_the_templates_are_configuration_not_code() -> None:
    assert TEMPLATES_FILE.suffix == ".yaml"
    assert set(load_templates()) >= {"servicenow", "jira", "generic"}


def test_servicenow_gets_an_incident_with_its_urgency() -> None:
    incident = render("servicenow", EVENT)
    assert incident["short_description"] == "[ARGOS] critical: sec-encryption-at-rest"
    assert incident["urgency"] == 1
    assert json.loads(incident["description"]) == EVENT
    assert render("servicenow", {**EVENT, "severity": "high"})["urgency"] == 2
    assert render("servicenow", {**EVENT, "severity": "low"})["urgency"] == 3


def test_jira_gets_an_issue() -> None:
    issue = render("jira", EVENT)
    assert issue["fields"]["summary"] == "[ARGOS] sec-encryption-at-rest"
    assert issue["fields"]["issuetype"] == {"name": "Bug"}


def test_generic_is_the_event_as_it_is() -> None:
    assert render("generic", EVENT) == EVENT


def test_a_field_the_event_does_not_carry_is_empty_not_an_error() -> None:
    sealed = {"type": "campaign_sealed", "campaign_id": "c-1"}
    assert render("jira", sealed)["fields"]["summary"] == "[ARGOS] "


def test_an_unknown_template_is_refused() -> None:
    with pytest.raises(TemplateError, match="remedy"):
        render("remedy", EVENT)
