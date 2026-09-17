"""Campaign domain activities: the I/O of the engine (ARG-007, ARG-044, ARG-046).

Workflows stay deterministic and free of I/O; everything that talks to a client system, to OPA or to
the database lives here. Three decisions carry the phase:

- a **budget or window** error is not a failure, it is a wait: it comes back as retryable;
- a **read-only violation** is not retryable: something is very wrong, and the unit freezes;
- the result is **minimised before returning**, so the workflow history only ever holds what the
  challenge declared to capture.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
from temporalio import activity
from temporalio.exceptions import ApplicationError

from argos_challenges.evaluator import evaluate
from argos_challenges.findings import announce, open_or_recur
from argos_challenges.probes import INVENTORY_QUERIES, minimise, probe_spec
from argos_challenges.store import persist_verdict
from argos_common.config import get_config
from argos_common.errors import ReadOnlyViolationError
from argos_common.journal_pg import PostgresJournal
from argos_common.secret_stores import SecretStore
from argos_connector.errors import BudgetExceededError, CircuitOpenError
from argos_inventory.discovery.probes import run_probe
from argos_inventory.graph.store import GraphStore
from argos_ontology.opa import OpaError
from argos_ontology.opa import evaluate as opa_evaluate
from argos_ontology.shacl import run_shapes

INTERNAL_PROBES = frozenset({"shacl", "inventory_query"})
WINDOW_POLL_SECONDS = 300


@activity.defn
async def smoke_probe(system: str) -> dict[str, Any]:
    """Exercise the worker -> activity -> result chain.

    Smoke workflow only: `fail-*` fails on the first two attempts and `always-fail` on every
    attempt, so the retry policy is exercised without mocks.
    """
    attempt = activity.info().attempt
    if system == "always-fail" or (system.startswith("fail-") and attempt < 3):
        raise RuntimeError(f"simulated smoke failure on attempt {attempt}")
    return {
        "system": system,
        "ok": True,
        "attempts": attempt,
        "at": datetime.now(UTC).isoformat(),
    }


@activity.defn
async def record_in_journal(action: str, payload: dict[str, Any]) -> int:
    journal = PostgresJournal(get_config().DATABASE_URL)
    actor = f"system:worker:{activity.info().task_queue}"
    return await asyncio.to_thread(journal.append, actor, action, payload)


class ChallengeActivities:
    """Activities of a campaign, bound to a database, a secret store and an OPA server."""

    def __init__(
        self,
        dsn: str,
        secrets: SecretStore,
        opa_url: str | None = None,
        bus: Any | None = None,
    ) -> None:
        self._dsn = dsn
        self._secrets = secrets
        self._opa_url = opa_url or get_config().OPA_URL
        self._bus = bus

    # ---------- probes ----------

    def _internal_probe(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        probe = unit["probe"]
        kind = str(probe["kind"])
        params = dict(probe.get("params", {}))
        if kind == "shacl":
            findings = run_shapes(GraphStore(self._dsn))
            shape = params.get("shape")
            rows = [
                {"node": finding.node, "shape": finding.shape, "severity": finding.severity}
                for finding in findings
                if shape is None or finding.shape == shape
            ]
            return {"ok": True, "data": {"count": len(rows), "rows": rows}}
        name = str(params.get("query", ""))
        statement = INVENTORY_QUERIES.get(name)
        if statement is None:
            raise ApplicationError(
                f"unknown inventory query: {name!r}", type="UnknownQuery", non_retryable=True
            )
        arguments = {
            "snapshot_id": params.get("snapshot_id"),
            "system_id": unit["system_id"],
        }
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(statement, arguments).fetchone()
        return {"ok": True, "data": {"count": 0 if row is None else int(row[0])}}

    def _run_probe(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        if str(unit["probe"]["kind"]) in INTERNAL_PROBES:
            answer = self._internal_probe(unit)
            answer["data"] = minimise(answer["data"], unit["evidence"]["capture"])
            return answer
        try:
            result = run_probe(self._dsn, self._secrets, str(unit["system_id"]), probe_spec(unit))
        except ReadOnlyViolationError as exc:
            PostgresJournal(self._dsn).append(
                "system:campaign",
                "probe.readonly_violation",
                {"unit": str(unit["unit_id"]), "system": str(unit["system_id"])},
            )
            raise ApplicationError(str(exc), type="ReadOnlyViolation", non_retryable=True) from exc
        except (BudgetExceededError, CircuitOpenError) as exc:
            # Not a failure: the system is protecting itself, so the unit waits and comes back.
            raise ApplicationError(str(exc), type=type(exc).__name__) from exc
        return {
            "ok": result.ok,
            "probe_id": result.probe_id,
            "journal_seq": result.journal_seq,
            "duration_ms": result.duration_ms,
            "data": minimise(result.data, unit["evidence"]["capture"]),
        }

    @activity.defn(name="probe")
    async def probe(self, unit: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._run_probe, unit)

    @activity.defn(name="wait_window")
    async def wait_window(self, system_id: str) -> None:
        """Wait for the agreed window of a system, with a heartbeat: a wait is not a failure."""
        from argos_inventory.discovery.probes import load_system  # local: only needed here

        while True:
            system = await asyncio.to_thread(load_system, self._dsn, system_id)
            budget = dict(system.config.get("budget", {}))
            if not budget.get("windows"):
                return
            from argos_connector.budget import LoadBudget

            if LoadBudget(system_id, budget).in_window():
                return
            activity.heartbeat("waiting for the agreed window")
            await asyncio.sleep(WINDOW_POLL_SECONDS)

    # ---------- evaluation ----------

    def _decide(self, unit: Mapping[str, Any], probe_result: Mapping[str, Any]) -> dict[str, Any]:
        criterion = unit.get("criterion", {})
        decision: dict[str, Any] | None = None
        if "opa" in criterion and probe_result.get("ok"):
            package = str(criterion["opa"]["package"])
            input_doc = dict(criterion["opa"].get("input_map", {}))
            input_doc.setdefault("result", probe_result.get("data", {}))
            try:
                decision = opa_evaluate(package, input_doc, self._opa_url)
            except OpaError:
                decision = None
        verdict = evaluate(unit, probe_result, decision)
        verdict_id, created = persist_verdict(
            self._dsn,
            str(unit["campaign_id"]),
            unit,
            verdict,
            probe_journal_seq=probe_result.get("journal_seq"),
        )
        answer: dict[str, Any] = {
            "verdict_id": verdict_id,
            "created": created,
            "result": verdict.result,
            "verdict_hash": verdict.hash,
            "finding": None,
        }
        if verdict.result == "non_compliant":
            answer["finding"] = open_or_recur(
                self._dsn, str(unit["campaign_id"]), unit, verdict, verdict_id
            )
        return answer

    @activity.defn(name="evaluate")
    async def evaluate_unit(self, payload: dict[str, Any]) -> dict[str, Any]:
        unit = payload["unit"]
        probe_result = payload["probe_result"]
        answer = await asyncio.to_thread(self._decide, unit, probe_result)
        finding = answer.get("finding")
        if finding and finding.get("created") and self._bus is not None:
            await announce(self._bus, finding, str(unit["campaign_id"]))
        return answer
