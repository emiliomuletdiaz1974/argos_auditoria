"""ARG-048 · the closed state machine and the escalation of a recurring finding."""

import pytest

from argos_challenges.findings import (
    ESCALATION_CAMPAIGNS,
    SEVERITIES,
    STATUSES,
    TRANSITIONS,
    escalate,
    fingerprint,
)


def test_the_fingerprint_is_the_challenge_and_the_node() -> None:
    mark = fingerprint("ret-table-retention", "k-node-1")
    assert mark == fingerprint("ret-table-retention", "k-node-1")
    assert mark != fingerprint("ret-table-retention", "k-node-2")
    assert mark != fingerprint("ret-file-retention", "k-node-1")
    assert len(mark) == 64


def test_the_state_machine_is_closed_and_has_one_way_out() -> None:
    assert set(TRANSITIONS) == set(STATUSES)
    for origin, destinations in TRANSITIONS.items():
        assert destinations <= set(STATUSES), origin
    assert TRANSITIONS["closed_compliant"] == frozenset()
    assert "risk_accepted" in TRANSITIONS["open"]
    assert TRANSITIONS["risk_accepted"] == frozenset({"reopened"})


def test_a_finding_reaches_the_closure_only_through_the_verification() -> None:
    assert "closed_compliant" not in TRANSITIONS["open"]
    assert "closed_compliant" not in TRANSITIONS["in_remediation"]
    assert TRANSITIONS["pending_verification"] == frozenset({"closed_compliant", "reopened"})


@pytest.mark.parametrize(
    ("severity", "occurrences", "expected"),
    [
        ("low", 1, "low"),
        ("low", 2, "low"),
        ("low", ESCALATION_CAMPAIGNS, "medium"),
        ("medium", 4, "high"),
        ("high", 3, "critical"),
        ("critical", 9, "critical"),
    ],
)
def test_recurrence_across_campaigns_raises_the_severity(
    severity: str, occurrences: int, expected: str
) -> None:
    assert escalate(severity, occurrences) == expected
    assert SEVERITIES[0] == "low" and SEVERITIES[-1] == "critical"


def test_the_order_of_the_listing_speaks_the_same_ranks_as_the_code() -> None:
    from argos_challenges.findings import _LIST, ORDER_KEY_SQL, SEVERITY_RANK

    for severity, rank in SEVERITY_RANK.items():
        assert f"WHEN '{severity}' THEN {rank}" in ORDER_KEY_SQL
    assert " ".join(_LIST.split()).count(" ".join(ORDER_KEY_SQL.split())) == 2


def test_a_person_never_reaches_what_only_the_re_run_decides() -> None:
    from argos_challenges.findings import VERIFICATION_ONLY, person_transitions

    for status in TRANSITIONS:
        assert not set(person_transitions(status)) & VERIFICATION_ONLY
    assert person_transitions("pending_verification") == []
