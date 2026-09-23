"""ARG-043 · the progress of a campaign tells which systems are paused, and why."""

from argos_challenges.workflows import CampaignWorkflow


def test_a_paused_system_shows_in_the_progress_with_its_reason() -> None:
    campaign = CampaignWorkflow()
    campaign.circuit_open("s-1", "latencia p50 de 900 ms")
    campaign.circuit_open("s-2")
    assert campaign.progress()["paused"] == [
        {"system_id": "s-1", "reason": "latencia p50 de 900 ms"},
        {"system_id": "s-2", "reason": ""},
    ]


def test_a_system_whose_circuit_closes_is_no_longer_paused() -> None:
    campaign = CampaignWorkflow()
    campaign.circuit_open("s-1", "latencia")
    campaign.circuit_closed("s-1")
    assert campaign.progress()["paused"] == []


def test_a_pause_does_not_outlive_the_cooldown_of_the_connector() -> None:
    """The connector reopens its circuit by itself; the campaign cannot wait for ever.

    Nobody sends `circuit_closed` today —the connector only announces the opening—, so a pause
    that never expired would hold a campaign until someone noticed. It lasts what the connector's
    cooldown lasts, and then the system is tried again.
    """
    from argos_challenges.workflows import PAUSE_MAX_SECONDS
    from argos_connector.budget import DEFAULTS

    assert float(DEFAULTS["open_cooldown_s"]) <= PAUSE_MAX_SECONDS
