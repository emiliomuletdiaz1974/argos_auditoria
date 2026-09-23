"""Put a test campaign where the engine would have it: approved and running.

Tests that build a campaign by hand (without the workflow) still have to follow its rules: only a
running campaign is sealed, and only the planned units of a running campaign with its gates approved
are evaluated (F09-23).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from argos_challenges.store import (
    campaign_record,
    grant_approval,
    request_approval,
    save_units,
    set_status,
)

APPROVER = "user:dpo"


def running(dsn: str, campaign_id: str, units: Sequence[Mapping[str, Any]] = ()) -> None:
    """Plan `units`, approve the start and move the campaign to running."""
    if units:
        save_units(dsn, campaign_id, list(units))
    request_approval(dsn, campaign_id, "start", {"units": len(units)})
    grant_approval(dsn, campaign_id, "start", APPROVER, 1)
    status = campaign_record(dsn, campaign_id)["status"]
    if status == "planned":
        set_status(dsn, campaign_id, "pinned")
        status = "pinned"
    if status == "pinned":
        set_status(dsn, campaign_id, "running")
