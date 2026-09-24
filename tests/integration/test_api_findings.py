"""ARG-076 · findings over the v1: the whole why, the transitions a person may take, and closure
only by running the challenge again.

A finding closed by hand is an opinion; a finding closed because the same challenge passed is
evidence. That is why no route closes one: the API refuses `closed_compliant` and `reopened` from a
person, the domain refuses them from any `user:` actor, and `verify` hands the finding to the
remediation run of ARG-049, the only one that can move it there.
"""

from datetime import date, timedelta
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator
from argos_challenges.activities import ChallengeActivities
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import FindingError, open_or_recur, transition
from argos_challenges.store import create_campaign, persist_verdict, pin_campaign, save_units
from argos_common.journal_pg import PostgresJournal

from .inventory_helpers import secret_store

pytestmark = pytest.mark.integration

SYSTEM = "00000000-0000-4000-8000-000000000001"
PROBE = {"ok": True, "data": {"rows": [{"ssl": "off"}]}}


def _unit(campaign_id: str, node_key: str) -> dict[str, Any]:
    return {
        "unit_id": node_key.ljust(64, "0")[:64],
        "campaign_id": campaign_id,
        "challenge_id": "sec-encryption-in-transit",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-1",
        "system_id": SYSTEM,
        "node_key": node_key,
        "probe": {
            "kind": "sql",
            "target": "public.patients",
            "statement": "SHOW ssl",
            "params": {},
        },
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None,
        "severity": "high",
    }


class Runner:
    def __init__(self) -> None:
        self.remediations: list[dict[str, Any]] = []

    async def remediate(self, scope: dict[str, Any]) -> str:
        self.remediations.append(scope)
        return f"remediation-{scope['finding_id']}"


class PersonValidator:
    def validate(self, token: str) -> Identity:
        role, _, person = token.partition(":")
        return Identity(
            sub=person or role,
            name=person or role,
            roles=frozenset({role}),
            amr=frozenset({"pwd", "otp"}),
        )


def _as(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{role}"}


def _finding(
    dsn: str, node_key: str, unit_changes: dict[str, Any] | None = None, probe: Any = PROBE
) -> dict[str, Any]:
    """A non-compliant verdict, with the journal entry of the question that produced it."""
    campaign_id = create_campaign(dsn, f"Campaña {node_key}", {}, "user:campaign_manager")
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    unit = {**_unit(campaign_id, node_key), **(unit_changes or {})}
    save_units(dsn, campaign_id, [unit])
    seq = PostgresJournal(dsn).append("system:probe", "probe.issued", {"unit": unit["unit_id"]})
    verdict = evaluate(unit, probe)
    verdict_id, _ = persist_verdict(dsn, campaign_id, unit, verdict, probe_journal_seq=seq)
    finding = open_or_recur(dsn, campaign_id, unit, verdict, verdict_id)
    return {**finding, "journal_seq": seq, "campaign_id": campaign_id}


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def api(migrated_db: str, runner: Runner) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=migrated_db, campaign_runner=runner))


def test_the_list_puts_the_worst_first_and_filters(api: TestClient, migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-list-0001")
    page = api.get(
        f"{API_PREFIX}/findings",
        params={"status": "open", "severity": finding["severity"], "limit": 200},
        headers=_as("read_only_auditor"),
    )
    assert page.status_code == 200
    items = page.json()["items"]
    assert finding["id"] in [item["id"] for item in items]
    assert all(item["status"] == "open" for item in items)
    ranks = [(item["severity_rank"], item["occurrences"]) for item in items]
    assert ranks == sorted(ranks, reverse=True)


def test_a_finding_carries_its_whole_why(api: TestClient, migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-why-0001")
    answer = api.get(f"{API_PREFIX}/findings/{finding['id']}", headers=_as("dpo_reviewer"))
    assert answer.status_code == 200
    body = answer.json()

    verdict = body["verdict"]
    assert verdict["result"] == "non_compliant"
    detail = verdict["verdict"]["detail"]
    assert (detail["observed"], detail["expected"]) == ("off", "on"), "the values it saw"
    assert verdict["probe_journal"]["seq"] == finding["journal_seq"]
    assert verdict["probe_journal"]["action"] == "probe.issued"

    obligation = body["obligation"]
    assert obligation["id"] == "OBL-RGPD-32-1"
    assert obligation["norm"] and obligation["article"]

    assert set(body["allowed_transitions"]) == {"in_remediation", "risk_accepted"}


def test_a_sampled_finding_carries_its_sampling_declaration(
    api: TestClient, migrated_db: str
) -> None:
    sampled = {
        "criterion": {"threshold": {"field": "count", "operator": "==", "value": 0}},
        "sampling": {"population": 1200, "sample": 300, "confidence": "0.95"},
    }
    probe = {"ok": True, "data": {"count": 4}}
    finding = _finding(migrated_db, "k-sampled-0001", sampled, probe)
    body = api.get(f"{API_PREFIX}/findings/{finding['id']}", headers=_as("dpo_reviewer")).json()
    sampling = body["verdict"]["sampling"]
    assert (sampling["population"], sampling["sample"], sampling["failures"]) == (1200, 300, 4)
    assert sampling["confidence"] == "0.95"


def test_a_reopened_finding_shows_its_history(api: TestClient, migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-history-0001")
    expiry = date.today() + timedelta(days=30)
    transition(migrated_db, finding["id"], "risk_accepted", "user:dpo", "aceptado", expiry)
    transition(migrated_db, finding["id"], "reopened", "system:risk-expiry")

    body = api.get(f"{API_PREFIX}/findings/{finding['id']}", headers=_as("dpo_reviewer")).json()
    history = body["history"]
    assert [step["action"] for step in history] == [
        "finding.open",
        "finding.transition",
        "finding.transition",
    ]
    assert [step["to"] for step in history] == ["open", "risk_accepted", "reopened"]
    assert history[1]["actor"] == "user:dpo"
    assert history[2]["actor"] == "system:risk-expiry"
    seqs = [step["seq"] for step in history]
    assert seqs == sorted(seqs), "in the order the journal wrote them"


def test_an_unknown_finding_is_a_404(api: TestClient) -> None:
    answer = api.get(
        f"{API_PREFIX}/findings/00000000-0000-4000-8000-0000000000ff", headers=_as("dpo_reviewer")
    )
    assert answer.status_code == 404


def test_a_person_cannot_close_a_finding(api: TestClient, migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-close-0001")
    path = f"{API_PREFIX}/findings/{finding['id']}/transition"
    for to in ("in_remediation", "pending_verification"):
        assert api.post(path, json={"to": to}, headers=_as("dpo_reviewer")).status_code == 200

    detail = api.get(f"{API_PREFIX}/findings/{finding['id']}", headers=_as("dpo_reviewer"))
    assert detail.json()["allowed_transitions"] == [], "from here only the re-run moves it"

    for to in ("closed_compliant", "reopened"):
        refused = api.post(path, json={"to": to}, headers=_as("dpo_reviewer"))
        assert refused.status_code == 409, to
        assert "re-run" in refused.json()["detail"]


def test_the_domain_also_refuses_a_person_closing_it(migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-domain-0001")
    transition(migrated_db, finding["id"], "in_remediation", "user:dpo")
    transition(migrated_db, finding["id"], "pending_verification", "user:dpo")
    with pytest.raises(FindingError, match="re-run"):
        transition(migrated_db, finding["id"], "closed_compliant", "user:dpo")
    transition(migrated_db, finding["id"], "closed_compliant", "system:remediation")


def test_accepting_a_risk_needs_a_reason_and_an_expiry(api: TestClient, migrated_db: str) -> None:
    finding = _finding(migrated_db, "k-risk-0001")
    path = f"{API_PREFIX}/findings/{finding['id']}/transition"
    tomorrow = (date.today() + timedelta(days=30)).isoformat()

    no_reason = api.post(
        path, json={"to": "risk_accepted", "risk_expiry": tomorrow}, headers=_as("dpo_reviewer")
    )
    assert no_reason.status_code == 422
    no_expiry = api.post(
        path, json={"to": "risk_accepted", "note": "compensado"}, headers=_as("dpo_reviewer")
    )
    assert no_expiry.status_code == 422

    accepted = api.post(
        path,
        json={
            "to": "risk_accepted",
            "note": "control compensatorio documentado",
            "risk_expiry": tomorrow,
        },
        headers=_as("dpo_reviewer"),
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"finding_id": finding["id"], "from": "open", "to": "risk_accepted"}


def test_verifying_hands_the_finding_to_the_re_run(
    api: TestClient, runner: Runner, migrated_db: str
) -> None:
    finding = _finding(migrated_db, "k-verify-0001")
    verify = f"{API_PREFIX}/findings/{finding['id']}/verify"

    early = api.post(verify, headers=_as("campaign_manager"))
    assert early.status_code == 409, "only a finding the client says is fixed is verified"

    transition(migrated_db, finding["id"], "in_remediation", "user:dpo")
    transition(migrated_db, finding["id"], "pending_verification", "user:dpo")
    launched = api.post(verify, headers=_as("campaign_manager"))
    assert launched.status_code == 200
    assert launched.json()["workflow_id"] == f"remediation-{finding['id']}"
    [scope] = runner.remediations
    assert scope["finding_id"] == finding["id"]
    assert scope["requested_by"] == "user:campaign_manager"


def test_the_re_run_of_one_finding_brings_back_only_its_unit(migrated_db: str) -> None:
    chosen = _finding(migrated_db, "k-only-0001")
    other = _finding(migrated_db, "k-only-0002")
    for finding in (chosen, other):
        transition(migrated_db, finding["id"], "in_remediation", "user:dpo")
        transition(migrated_db, finding["id"], "pending_verification", "user:dpo")

    started = ChallengeActivities(migrated_db, secret_store())._start_remediation(
        {"finding_id": chosen["id"], "requested_by": "user:campaign_manager"}
    )
    assert [entry["finding_id"] for entry in started["units"]] == [chosen["id"]]


def test_reading_findings_leaves_no_entry(api: TestClient, migrated_db: str) -> None:
    _finding(migrated_db, "k-read-0001")
    with psycopg.connect(migrated_db) as conn:
        before = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    api.get(f"{API_PREFIX}/findings", headers=_as("read_only_auditor"))
    with psycopg.connect(migrated_db) as conn:
        after = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    assert before == after
