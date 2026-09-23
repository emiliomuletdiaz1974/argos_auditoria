"""Campaign workflows (ARG-007, ARG-043): deterministic and I/O-free.

The campaign is a process of days with people inside: it survives restarts (Temporal does that), it
stops at the gates until a DPO approves, it steps aside when a client system opens its circuit
breaker, and it ends by sealing what it measured. Everything it does goes through activities; the
workflow itself only decides and waits.
"""

import contextlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from .activities import record_in_journal, smoke_probe

RETRY_POLICY = RetryPolicy(
    maximum_attempts=3, backoff_coefficient=2.0, initial_interval=timedelta(milliseconds=200)
)
_TIMEOUT = timedelta(seconds=30)


@workflow.defn
class SmokeCampaign:
    @workflow.run
    async def run(self, systems: list[str]) -> list[dict[str, Any]]:
        workflow_id = workflow.info().workflow_id
        await workflow.execute_activity(
            record_in_journal,
            args=["campaign.smoke.start", {"systems": systems, "workflow_id": workflow_id}],
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        results: list[dict[str, Any]] = []
        for system in systems:
            results.append(
                await workflow.execute_activity(
                    smoke_probe,
                    system,
                    start_to_close_timeout=_TIMEOUT,
                    retry_policy=RETRY_POLICY,
                )
            )
        await workflow.execute_activity(
            record_in_journal,
            args=["campaign.smoke.end", {"workflow_id": workflow_id, "probes": len(results)}],
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return results


CAMPAIGN_TIMEOUT = timedelta(minutes=30)
GATE_TIMEOUT = timedelta(hours=72)
# A gate is also checked every so often, not only when a signal arrives: a remediation run has no
# workflow the API can signal, and a lost signal must not hold a campaign.
GATE_POLL = timedelta(seconds=5)
# What the connector waits before trying a source whose circuit it opened (ARG-013): the campaign
# waits the same, so a pause nobody closes does not become an eternal one.
PAUSE_MAX_SECONDS = 300.0
PAUSE_MAX = timedelta(seconds=PAUSE_MAX_SECONDS)
PROBE_TIMEOUT = timedelta(minutes=30)
# Once every injection is confirmed as reverted, the markers of the subject are looked for in the
# client's systems; if they are still there, the next look waits this long, not a gate poll.
REVERSION_RECHECK = timedelta(minutes=5)
START_GATE = "start"
SAMPLING_GATE = "sampling"
PROBE_RETRY = RetryPolicy(
    maximum_attempts=3,
    backoff_coefficient=2.0,
    initial_interval=timedelta(seconds=1),
    non_retryable_error_types=["ReadOnlyViolation", "UnknownQuery"],
)


async def await_reversions(campaign_id: str, progress: dict[str, Any] | None = None) -> None:
    """Wait until the synthetic subject is verified as gone from every system it was injected in.

    The client confirms each reversion; the campaign then looks for the subject read-only and is
    sealed only when nothing is left (security review F09-02, SEC-015). A campaign without
    injections goes straight through.
    """
    deadline = workflow.now() + GATE_TIMEOUT
    while True:
        check = await workflow.execute_activity(
            "check_reversions",
            campaign_id,
            start_to_close_timeout=PROBE_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        if not any(check.values()):
            return
        if progress is not None:
            progress["status"] = "awaiting:revert"
        if workflow.now() >= deadline:
            raise ApplicationError(
                "the synthetic subject was not verified as reverted in time", non_retryable=True
            )
        await workflow.sleep(GATE_POLL if check["pending"] else REVERSION_RECHECK)


async def await_gate(
    campaign_id: str,
    gate: str,
    payload: dict[str, Any],
    approved: set[str],
    progress: dict[str, Any] | None = None,
) -> None:
    """Ask for a gate and wait until the approvals people recorded open it.

    A signal only wakes the wait early; what opens the gate is `check_gate`, which reads the
    recorded approvals (whoever reaches Temporal can send a signal). The campaign says it awaits
    the gate only once the request is stored: a person who approves on seeing that state always
    finds the request to approve.
    """
    await workflow.execute_activity(
        "request_approval",
        {"campaign_id": campaign_id, "gate": gate, "payload": payload},
        start_to_close_timeout=_TIMEOUT,
        retry_policy=RETRY_POLICY,
    )
    if progress is not None:
        progress["status"] = f"awaiting:{gate}"
    deadline = workflow.now() + GATE_TIMEOUT
    while True:
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(lambda: gate in approved, timeout=GATE_POLL)
        opened = await workflow.execute_activity(
            "check_gate",
            {"campaign_id": campaign_id, "gate": gate},
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        if opened:
            return
        approved.discard(gate)
        if workflow.now() >= deadline:
            raise ApplicationError(f"the gate {gate} was not approved in time", non_retryable=True)


@workflow.defn
class SystemRun:
    """The units of one system, one after another: the budget already limits the pace."""

    @workflow.run
    async def run(
        self, campaign_id: str, system_id: str, units: list[dict[str, Any]]
    ) -> dict[str, Any]:
        done = findings = 0
        for unit in units:
            await workflow.execute_activity(
                "wait_window", system_id, start_to_close_timeout=timedelta(hours=24)
            )
            probe_result = await workflow.execute_activity(
                "probe",
                unit,
                start_to_close_timeout=PROBE_TIMEOUT,
                retry_policy=PROBE_RETRY,
            )
            verdict = await workflow.execute_activity(
                "evaluate",
                {"unit": unit, "probe_result": probe_result},
                start_to_close_timeout=_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            done += 1
            findings += 1 if verdict.get("finding") else 0
        return {"system_id": system_id, "done": done, "findings": findings}


@workflow.defn
class CampaignWorkflow:
    """Prepare, ask the gates, run the systems and seal."""

    def __init__(self) -> None:
        self._approved: set[str] = set()
        self._paused: dict[str, str] = {}  # system -> why its circuit opened
        self._progress: dict[str, Any] = {"status": "preparing", "done": 0, "findings": 0}

    @workflow.signal
    def approve(self, gate: str) -> None:
        self._approved.add(gate)

    @workflow.signal
    def circuit_open(self, system_id: str, reason: str = "") -> None:
        # The reason is optional so a sender that only names the system keeps working.
        self._paused[system_id] = reason

    @workflow.signal
    def circuit_closed(self, system_id: str) -> None:
        self._paused.pop(system_id, None)

    @workflow.query
    def progress(self) -> dict[str, Any]:
        paused = [{"system_id": s, "reason": r} for s, r in sorted(self._paused.items())]
        return {**self._progress, "paused": paused}

    async def _gate(self, campaign_id: str, gate: str, payload: dict[str, Any]) -> None:
        await await_gate(campaign_id, gate, payload, self._approved, self._progress)

    async def _run_system(
        self, campaign_id: str, system_id: str, units: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # A paused system does not spin: it waits until its circuit closes again, and no longer
        # than the cooldown the connector itself uses to try the source again. Nobody sends
        # `circuit_closed` today —the connector only announces the opening—, so a pause without
        # an end would hold the campaign for ever.
        if system_id in self._paused:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: system_id not in self._paused, timeout=PAUSE_MAX
                )
            self._paused.pop(system_id, None)
        result: dict[str, Any] = await workflow.execute_child_workflow(
            SystemRun.run,
            args=[campaign_id, system_id, units],
            id=f"{workflow.info().workflow_id}-{system_id}",
        )
        self._progress["done"] += result["done"]
        self._progress["findings"] += result["findings"]
        return result

    @workflow.run
    async def run(self, campaign_id: str) -> dict[str, Any]:
        prepared = await workflow.execute_activity(
            "prepare_campaign",
            campaign_id,
            start_to_close_timeout=CAMPAIGN_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        units: list[dict[str, Any]] = prepared["units"]
        self._progress["total"] = len(units)
        await self._gate(
            campaign_id,
            START_GATE,
            {"units": len(units), "unverifiable": prepared["unverifiable"]},
        )
        if prepared["needs_sampling"]:
            await self._gate(campaign_id, SAMPLING_GATE, {"units": len(units)})
        await workflow.execute_activity(
            "set_campaign_status",
            {"campaign_id": campaign_id, "status": "running"},
            start_to_close_timeout=_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._progress["status"] = "running"

        by_system: dict[str, list[dict[str, Any]]] = {}
        for unit in units:
            by_system.setdefault(str(unit["system_id"]), []).append(unit)
        for system_id, system_units in sorted(by_system.items()):
            await self._run_system(campaign_id, system_id, system_units)

        await await_reversions(campaign_id, self._progress)
        sealed = await workflow.execute_activity(
            "seal_campaign",
            campaign_id,
            start_to_close_timeout=CAMPAIGN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        self._progress["status"] = "sealed"
        return {"campaign_id": campaign_id, "seal": sealed["seal"], **self._progress}


@workflow.defn
class RemediationRun:
    """Verify what the client says it fixed, with the same challenge that found it (ARG-049).

    The campaign is not relaunched: exactly the non-compliant units come back. A verdict that is
    neither compliant nor non-compliant leaves the finding where it was, with its reason.

    It goes through the gates of any campaign: a DPO approves the start, and two people the
    sampling when a unit samples. Otherwise a campaign manager alone could re-run probes against
    the client until one closes the finding (security review F09-02, SEC-010). And it is sealed
    like any campaign, so what closed a finding is evidence too (SEC-036).
    """

    def __init__(self) -> None:
        self._approved: set[str] = set()

    @workflow.signal
    def approve(self, gate: str) -> None:
        self._approved.add(gate)

    @workflow.run
    async def run(self, scope: dict[str, Any]) -> dict[str, Any]:
        started = await workflow.execute_activity(
            "start_remediation",
            scope,
            start_to_close_timeout=CAMPAIGN_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        summary = {"verified": 0, "closed": 0, "reopened": 0, "unchanged": 0}
        campaign_id = started["campaign_id"]
        if campaign_id is not None and started["units"]:
            units = [entry["unit"] for entry in started["units"]]
            await await_gate(campaign_id, "start", {"units": len(units)}, self._approved)
            if any(unit.get("needs_approval") for unit in units):
                await await_gate(campaign_id, "sampling", {"units": len(units)}, self._approved)
            await workflow.execute_activity(
                "set_campaign_status",
                {"campaign_id": campaign_id, "status": "running"},
                start_to_close_timeout=_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        for entry in started["units"]:
            unit = entry["unit"]
            probe_result = await workflow.execute_activity(
                "probe", unit, start_to_close_timeout=PROBE_TIMEOUT, retry_policy=PROBE_RETRY
            )
            verdict = await workflow.execute_activity(
                "evaluate",
                {"unit": unit, "probe_result": probe_result},
                start_to_close_timeout=_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            summary["verified"] += 1
            if verdict["result"] == "compliant":
                destination = "closed_compliant"
                summary["closed"] += 1
            elif verdict["result"] == "non_compliant":
                destination = "reopened"
                summary["reopened"] += 1
            else:
                summary["unchanged"] += 1
                continue
            await workflow.execute_activity(
                "transition_finding",
                {"finding_id": entry["finding_id"], "to": destination},
                start_to_close_timeout=_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
        if campaign_id is not None and started["units"]:
            await await_reversions(campaign_id)
            await workflow.execute_activity(
                "seal_campaign",
                campaign_id,
                start_to_close_timeout=CAMPAIGN_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
        return {"campaign_id": started["campaign_id"], **summary}
