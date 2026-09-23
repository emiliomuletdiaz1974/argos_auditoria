"""Every worker that runs a campaign registers every activity the campaign executes.

A workflow that asks for an activity its worker does not know does not fail at start: it fails at
that step, waiting on a queue nobody serves. This is how the demonstration lost the gate check that
the 2026-09-18 audit added (F09-17). The names come from the workflow source and the activity
definitions, not from a list copied here.
"""

import re
from pathlib import Path

from argos_challenges.activities import ChallengeActivities

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "services" / "challenge-engine" / "argos_challenges" / "workflows.py"
RUNNERS = [
    ROOT / "services" / "challenge-engine" / "argos_challenges" / "worker.py",
    ROOT / "tools" / "demo" / "run_mvp_demo.py",
]
CAMPAIGN_CLASSES = ("SystemRun", "CampaignWorkflow")
EXECUTED = re.compile(r"execute_activity\(\s*\"(\w+)\"")


def _executed_by_the_campaign() -> set[str]:
    """Activities the campaign classes run, directly or through a module function they call."""
    source = WORKFLOWS.read_text("utf-8")
    parts = re.split(r"^(?:class|async def|def) (\w+)", source, flags=re.MULTILINE)
    blocks = dict(zip(parts[1::2], parts[2::2], strict=True))
    campaign = "".join(blocks[name] for name in CAMPAIGN_CLASSES)
    helpers = [body for name, body in blocks.items() if re.search(rf"\b{name}\(", campaign)]
    return set(EXECUTED.findall(campaign + "".join(helpers)))


def _activity_names() -> dict[str, str]:
    """Attribute of ChallengeActivities -> name Temporal knows it by."""
    names = {}
    for attribute in dir(ChallengeActivities):
        definition = getattr(
            getattr(ChallengeActivities, attribute), "__temporal_activity_definition", None
        )
        if definition is not None:
            names[attribute] = definition.name
    return names


def test_the_campaign_executes_known_activities() -> None:
    executed = _executed_by_the_campaign()
    assert "check_gate" in executed
    assert executed <= set(_activity_names().values())


def test_every_campaign_runner_registers_what_the_campaign_executes() -> None:
    executed = _executed_by_the_campaign()
    by_attribute = _activity_names()
    for runner in RUNNERS:
        source = runner.read_text("utf-8")
        registered = {
            by_attribute[attr]
            for attr in re.findall(r"\b\w+\.(\w+),", source)
            if attr in by_attribute
        }
        missing = executed - registered
        assert not missing, f"{runner.relative_to(ROOT)} does not register {sorted(missing)}"
