"""SEC-008 · separation of duties holds by person, not only by role (F09-24).

A person given two roles by mistake still does not approve what they themselves asked for.
"""

import pytest

from argos_challenges.store import (
    CampaignStateError,
    create_campaign,
    grant_approval,
    request_approval,
)

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SECOND_DPO = "user:dpo-2"


def test_whoever_created_a_campaign_does_not_approve_its_start(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña propia", {}, MANAGER)
    request_approval(migrated_db, campaign_id, "start", {"units": 1})
    with pytest.raises(CampaignStateError, match="created"):
        grant_approval(migrated_db, campaign_id, "start", MANAGER, 1)
    assert grant_approval(migrated_db, campaign_id, "start", DPO, 1) == (1, True)


def test_whoever_created_a_campaign_does_not_count_in_its_sampling(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña muestreada", {}, DPO)
    request_approval(migrated_db, campaign_id, "sampling", {"units": 1})
    with pytest.raises(CampaignStateError, match="created"):
        grant_approval(migrated_db, campaign_id, "sampling", DPO, 2)
    grant_approval(migrated_db, campaign_id, "sampling", SECOND_DPO, 2)
    assert grant_approval(migrated_db, campaign_id, "sampling", "user:dpo-3", 2) == (2, True)
