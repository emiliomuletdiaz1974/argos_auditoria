"""ARG-044/046 · the probe and evaluation activities against the simulated sources."""

import asyncio
from typing import Any

import pytest
from temporalio.exceptions import ApplicationError

from argos_challenges.activities import ChallengeActivities
from argos_challenges.store import create_campaign, pin_campaign
from argos_common.journal_pg import PostgresJournal

from .campaign_helpers import running
from .inventory_helpers import secret_store
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
CAMPAIGN_NAME = "Campaña de actividades"


def _unit(campaign_id: str, system_id: str, **changes: Any) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "unit_id": "a" * 64,
        "campaign_id": campaign_id,
        "challenge_id": "sec-encryption-in-transit",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": system_id,
        "node_key": "k-node-0001",
        "probe": {
            "kind": "check_config",
            "target": "clinic",
            "statement": None,
            "params": {"check": "encryption_at_rest"},
        },
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "evidence": {"capture": ["configuration"], "minimisation": "Solo parámetros de cifrado."},
        "severity": "high",
        "sampling": None,
        "needs_approval": False,
        "preconditions": [],
    }
    unit.update(changes)
    return unit


@pytest.fixture
def campaign(migrated_db: str) -> tuple[str, str, ChallengeActivities]:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    campaign_id = create_campaign(migrated_db, CAMPAIGN_NAME, {}, MANAGER)
    pin_campaign(
        migrated_db,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    activities = ChallengeActivities(migrated_db, secret_store())
    return campaign_id, system_id, activities


def test_a_configuration_probe_returns_only_what_the_challenge_declared(
    campaign: tuple[str, str, ChallengeActivities],
) -> None:
    campaign_id, system_id, activities = campaign
    unit = _unit(campaign_id, system_id)
    result = asyncio.run(activities.probe(unit))
    assert result["ok"] is True
    assert set(result["data"]) <= {"rows"}
    assert result["journal_seq"] > 0


def test_the_evaluation_persists_one_verdict_however_many_times_it_runs(
    campaign: tuple[str, str, ChallengeActivities],
) -> None:
    campaign_id, system_id, activities = campaign
    unit = _unit(campaign_id, system_id)
    running(activities._dsn, campaign_id, [unit])  # only a planned unit of a running campaign
    probe_result = asyncio.run(activities.probe(unit))
    first = asyncio.run(activities.evaluate_unit({"unit": unit, "probe_result": probe_result}))
    second = asyncio.run(activities.evaluate_unit({"unit": unit, "probe_result": probe_result}))
    assert first["created"] is True and second["created"] is False
    assert first["verdict_id"] == second["verdict_id"]
    assert first["result"] in {"compliant", "non_compliant", "inconclusive"}


def test_an_unknown_internal_question_is_refused_without_retrying(
    campaign: tuple[str, str, ChallengeActivities],
) -> None:
    campaign_id, system_id, activities = campaign
    unit = _unit(
        campaign_id,
        system_id,
        probe={
            "kind": "inventory_query",
            "target": "argos",
            "statement": None,
            "params": {"query": "drop_everything"},
        },
    )
    with pytest.raises(ApplicationError) as error:
        asyncio.run(activities.probe(unit))
    assert error.value.non_retryable and error.value.type == "UnknownQuery"


def test_a_probe_of_a_system_that_is_not_registered_fails_clearly(
    campaign: tuple[str, str, ChallengeActivities],
) -> None:
    campaign_id, _, activities = campaign
    unit = _unit(campaign_id, "00000000-0000-4000-8000-0000000000ff")
    with pytest.raises(LookupError):
        asyncio.run(activities.probe(unit))


def test_the_probe_writes_its_previous_journal_entry(
    migrated_db: str, campaign: tuple[str, str, ChallengeActivities]
) -> None:
    campaign_id, system_id, activities = campaign
    unit = _unit(campaign_id, system_id)
    result = asyncio.run(activities.probe(unit))
    entries = {entry.seq: entry for entry in PostgresJournal(migrated_db).read(1, 500)}
    assert result["journal_seq"] in entries
    assert entries[result["journal_seq"]].action == "query.emit"
