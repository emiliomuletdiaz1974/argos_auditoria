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

from argos_challenges.client import client_parameters
from argos_challenges.compiler import compile_campaign
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import announce, open_or_recur, transition
from argos_challenges.library.catalog import load_library
from argos_challenges.probes import INVENTORY_QUERIES, minimise, probe_spec
from argos_challenges.seal import announce_seal, seal_campaign
from argos_challenges.snapshot_resolver import SnapshotSelectorResolver
from argos_challenges.store import (
    announce_approval,
    campaign_record,
    create_campaign,
    persist_verdict,
    pin_campaign,
    request_approval,
    save_units,
    set_status,
)
from argos_challenges.synthetic import campaign_subject
from argos_common.config import get_config
from argos_common.errors import ReadOnlyViolationError
from argos_common.journal_pg import PostgresJournal
from argos_common.secret_stores import SecretStore
from argos_connector.errors import BudgetExceededError, CircuitOpenError
from argos_inventory.discovery.probes import run_probe
from argos_inventory.graph.model import system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.snapshots import take_snapshot
from argos_ontology.library_hash import library_fingerprint
from argos_ontology.opa import OpaError
from argos_ontology.opa import evaluate as opa_evaluate
from argos_ontology.resolver import resolve as resolve_applicability
from argos_ontology.shacl import run_shapes
from argos_ontology.store import OntologyStore, version_in_force
from argos_ontology.traceability import load_challenge_catalog

INTERNAL_PROBES = frozenset({"shacl", "inventory_query"})
_DECLARED_TREATMENTS = "MATCH (s:System)-[:DECLARED_IN]->(t:Treatment) RETURN s.key, t.key"
_AI_SYSTEMS = "MATCH (a:AISystem) RETURN a.key, a.system_id"
_PENDING_UNITS = (
    "SELECT f.id::text, u.unit FROM argos.findings f "
    "JOIN argos.verdicts v ON v.id = f.last_verdict "
    "JOIN argos.campaign_units u ON u.campaign_id = v.campaign_id AND u.unit_id = v.unit_id "
    "WHERE f.status = 'pending_verification' "
    "AND (%(campaign)s::uuid IS NULL OR f.campaign_id = %(campaign)s::uuid) "
    "AND (%(finding)s::uuid IS NULL OR f.id = %(finding)s::uuid) ORDER BY f.id"
)
_SYSTEMS = (
    "SELECT id::text, name, kind, connection->>'connector', connection->'config' FROM argos.systems"
)


def _registered_systems(dsn: str) -> dict[str, dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_SYSTEMS).fetchall()
    return {
        str(row[0]): {
            "id": str(row[0]),
            "name": row[1],
            "kind": row[2],
            "connector": row[3],
            "config": row[4] or {},
        }
        for row in rows
    }


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


def _system_scope(store: GraphStore, system_id: str) -> frozenset[str]:
    """The nodes a coherence finding may talk about for one system: the system itself, the
    treatments it declares and the AI systems it holds. A campaign answers per system, so a gap
    in another one is not its verdict."""
    key = system_key(system_id)
    treatments = {
        str(row["treatment"])
        for row in store.query(_DECLARED_TREATMENTS, columns=("system", "treatment"))
        if str(row["system"]) == key
    }
    ai_systems = {
        str(row["key"])
        for row in store.query(_AI_SYSTEMS, columns=("key", "system_id"))
        if str(row["system_id"]) == system_id
    }
    return frozenset({key, *treatments, *ai_systems})


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

    # ---------- preparation ----------

    def _prepare(self, campaign_id: str) -> dict[str, Any]:
        store = GraphStore(self._dsn)
        snapshot = take_snapshot(store, self._dsn, f"campaign-{campaign_id}")
        ontology_version = version_in_force(self._dsn)
        library_version, library_sha256 = library_fingerprint()
        pin_campaign(
            self._dsn,
            campaign_id,
            snapshot_id=snapshot.id,
            snapshot_hash=snapshot.content_hash,
            ontology_version=ontology_version,
            library_version=library_version,
            library_sha256=library_sha256,
            applicability_run=None,
        )
        resolver = SnapshotSelectorResolver(self._dsn, snapshot.id)
        ontology = OntologyStore(self._dsn, ontology_version)
        campaign = campaign_record(self._dsn, campaign_id)
        run = resolve_applicability(
            self._dsn, ontology, resolver, campaign["scope"] or {}, campaign_id=campaign_id
        )
        nodes = {str(node["node_key"]): node for node in resolver.nodes}
        systems = _registered_systems(self._dsn)
        library = load_library()
        subject = campaign_subject(self._dsn, campaign_id)
        reserved = frozenset(load_challenge_catalog()) - frozenset(library)
        compiled = compile_campaign(
            campaign_id,
            run.plan,
            library,
            nodes,
            systems,
            {
                "campaign": {"snapshot_id": snapshot.id},
                "client": client_parameters(),
                "subject": subject.markers if subject is not None else {},
            },
            reserved=reserved,
        )
        save_units(self._dsn, campaign_id, compiled.units)
        return {
            "campaign_id": campaign_id,
            "snapshot_id": snapshot.id,
            "ontology_version": ontology_version,
            "library_version": library_version,
            "units": compiled.units,
            "unverifiable": compiled.unverifiable,
            "needs_sampling": any(unit["needs_approval"] for unit in compiled.units),
        }

    @activity.defn(name="prepare_campaign")
    async def prepare_campaign(self, campaign_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._prepare, campaign_id)

    @activity.defn(name="request_approval")
    async def request_approval(self, payload: dict[str, Any]) -> None:
        campaign_id, gate = str(payload["campaign_id"]), str(payload["gate"])
        opened = await asyncio.to_thread(
            request_approval, self._dsn, campaign_id, gate, dict(payload.get("payload", {}))
        )
        if opened and self._bus is not None:
            await announce_approval(self._bus, campaign_id, gate)

    @activity.defn(name="set_campaign_status")
    async def set_campaign_status(self, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(
            set_status, self._dsn, str(payload["campaign_id"]), str(payload["status"])
        )

    @activity.defn(name="seal_campaign")
    async def seal(self, campaign_id: str) -> dict[str, Any]:
        sealed = await asyncio.to_thread(seal_campaign, self._dsn, campaign_id)
        if self._bus is not None:
            await announce_seal(self._bus, sealed)
        return sealed

    # ---------- remediation ----------

    def _start_remediation(self, scope: Mapping[str, Any]) -> dict[str, Any]:
        """The units to re-run: exactly the ones that opened the findings awaiting verification.

        The unit is the one stored with the verdict, so the remediation is measured with the same
        challenge version that measured the problem, even if the library has moved on (ARG-049).
        """
        # One statement, three uses: a campaign, one finding, or everything awaiting verification.
        filters = {"campaign": scope.get("campaign_id"), "finding": scope.get("finding_id")}
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(_PENDING_UNITS, filters).fetchall()
        if not rows:
            return {"campaign_id": None, "units": []}
        origin = (
            campaign_record(self._dsn, str(scope["campaign_id"]))
            if scope.get("campaign_id")
            else None
        )
        campaign_id = create_campaign(
            self._dsn,
            f"Subsanación {scope.get('campaign_id', 'general')}",
            dict(scope),
            str(scope.get("requested_by", "user:remediation")),
        )
        pin_campaign(
            self._dsn,
            campaign_id,
            snapshot_id=(origin or {}).get("snapshot_id"),
            snapshot_hash=(origin or {}).get("snapshot_hash"),
            ontology_version=(origin or {}).get("ontology_version") or "0.0.0",
            library_version=(origin or {}).get("library_version") or "0.0.0",
            library_sha256=(origin or {}).get("library_sha256") or "0" * 64,
            applicability_run=None,
        )
        units: list[dict[str, Any]] = []
        for finding_id, unit in rows:
            work = dict(unit)
            work["campaign_id"] = campaign_id
            work["remediation"] = True
            units.append({"finding_id": str(finding_id), "unit": work})
        save_units(self._dsn, campaign_id, [dict(entry["unit"]) for entry in units])
        return {"campaign_id": campaign_id, "units": units}

    @activity.defn(name="start_remediation")
    async def start_remediation(self, scope: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._start_remediation, scope)

    @activity.defn(name="transition_finding")
    async def transition_finding(self, payload: dict[str, Any]) -> str:
        return await asyncio.to_thread(
            transition,
            self._dsn,
            str(payload["finding_id"]),
            str(payload["to"]),
            str(payload.get("actor", "system:remediation")),
        )

    # ---------- probes ----------

    def _internal_probe(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        probe = unit["probe"]
        kind = str(probe["kind"])
        params = dict(probe.get("params", {}))
        if kind == "shacl":
            store = GraphStore(self._dsn)
            findings = run_shapes(store)
            shape, severity = params.get("shape"), params.get("severity")
            scope = _system_scope(store, str(unit["system_id"]))
            rows = [
                {"node": finding.node, "shape": finding.shape, "severity": finding.severity}
                for finding in findings
                if (shape is None or finding.shape == shape)
                and (severity is None or finding.severity == severity)
                and finding.node in scope
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
        if row is None or row[0] is None:
            # A question ARGOS cannot answer is not a zero: the evaluator turns it into
            # `inconclusive` because the field is missing, never into `compliant`.
            return {"ok": True, "data": {}}
        return {"ok": True, "data": {"count": int(row[0])}}

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
                self._dsn,
                str(unit["campaign_id"]),
                unit,
                verdict,
                verdict_id,
                counts_as_recurrence=not bool(unit.get("remediation")),
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
