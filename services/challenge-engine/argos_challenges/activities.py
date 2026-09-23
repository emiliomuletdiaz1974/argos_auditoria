"""Campaign domain activities: the I/O of the engine (ARG-007, ARG-044, ARG-046).

Workflows stay deterministic and free of I/O; everything that talks to a client system, to OPA or to
the database lives here. Three decisions carry the phase:

- a **budget or window** error is not a failure, it is a wait: it comes back as retryable;
- a **read-only violation** is not retryable: something is very wrong, and the unit freezes;
- the result is **minimised before returning**, so the workflow history only ever holds what the
  challenge declared to capture.
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
from rdflib import Graph, Literal
from temporalio import activity
from temporalio.exceptions import ApplicationError

from argos_challenges.client import client_parameters
from argos_challenges.compiler import compile_campaign, connector_id
from argos_challenges.dsl import EVIDENCE_INPUT_KEYS
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import REMEDIATION_ACTOR, announce, open_or_recur, transition
from argos_challenges.library.catalog import load_library
from argos_challenges.probes import INVENTORY_QUERIES, minimise, probe_spec
from argos_challenges.seal import announce_seal, seal_campaign
from argos_challenges.snapshot_resolver import SnapshotSelectorResolver
from argos_challenges.store import (
    announce_approval,
    campaign_record,
    create_campaign,
    gate_is_open,
    persist_verdict,
    pin_campaign,
    request_approval,
    save_units,
    set_status,
    stored_unit,
)
from argos_challenges.synthetic import campaign_subject, injections
from argos_common.config import get_config
from argos_common.errors import ReadOnlyViolationError
from argos_common.journal_pg import PostgresJournal
from argos_common.secret_stores import SecretStore
from argos_connector.budget import CircuitListener
from argos_connector.errors import BudgetExceededError, CircuitOpenError
from argos_connector.events import bus_circuit_listener
from argos_connector.probes import ProbeSpec
from argos_inventory.discovery.probes import run_probe
from argos_inventory.graph.model import system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.snapshots import SnapshotRef, snapshot_nodes, take_snapshot
from argos_ontology.bundle import verify_on_disk, verify_running_policies
from argos_ontology.library_hash import library_fingerprint
from argos_ontology.opa import OpaError, loaded_policies
from argos_ontology.opa import evaluate as opa_evaluate
from argos_ontology.resolver import resolve as resolve_applicability
from argos_ontology.shacl import (
    G,
    N,
    export_graph,
    load_shapes,
    snapshot_data,
    store_snapshot_data,
    validate_graph,
)
from argos_ontology.store import OntologyStore, version_in_force
from argos_ontology.traceability import load_challenge_catalog
from argos_ontology.vocabulary import LIBRARY_DIR

INTERNAL_PROBES = frozenset({"shacl", "inventory_query"})
# Where the marker of a synthetic subject can be looked for after a reversion: the categories of
# the columns of the injection point, and the connectors whose `count` probe filters by value.
REVERSION_MARKERS: Mapping[str, str] = {
    "official_identifier": "national_id",
    "contact_data": "email",
    "financial_data": "iban",
}
REVERSION_CONNECTORS = frozenset({"rdbms.postgresql", "rdbms.generic"})
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


def _system_scope(data: Graph, system_id: str) -> frozenset[str]:
    """The nodes a coherence finding may talk about for one system: the system itself, the
    treatments it declares and the AI systems it holds. A campaign answers per system, so a gap
    in another one is not its verdict. Read from the data frozen with the snapshot."""
    key = system_key(system_id)
    prefix = str(N)
    treatments = {
        str(treatment).removeprefix(prefix) for treatment in data.objects(N[key], G.declared_in)
    }
    ai_systems = {
        str(node).removeprefix(prefix) for node in data.subjects(G.system_id, Literal(system_id))
    }
    return frozenset({key, *treatments, *ai_systems})


def _with_snapshot(value: Any, old: str, new: str) -> Any:
    """`value` with every reference to the snapshot `old` pointing to `new` instead."""
    if isinstance(value, Mapping):
        return {k: _with_snapshot(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_snapshot(item, old, new) for item in value]
    return new if value == old else value


@activity.defn
async def record_in_journal(action: str, payload: dict[str, Any]) -> int:
    journal = PostgresJournal(get_config().DATABASE_URL)
    actor = f"system:worker:{activity.info().task_queue}"
    return await asyncio.to_thread(journal.append, actor, action, payload)


def _canonical(unit: Mapping[str, Any]) -> str:
    return json.dumps(unit, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class ChallengeActivities:
    """Activities of a campaign, bound to a database, a secret store and an OPA server."""

    def __init__(
        self,
        dsn: str,
        secrets: SecretStore,
        opa_url: str | None = None,
        bus: Any | None = None,
        opa_token: str | None = None,
    ) -> None:
        self._dsn = dsn
        self._secrets = secrets
        if opa_url is None:
            config = get_config()
            opa_url = config.OPA_URL
            if opa_token is None and config.OPA_TOKEN is not None:
                opa_token = config.OPA_TOKEN.get_secret_value()
        self._opa_url = opa_url
        self._opa_token = opa_token
        self._bus = bus

    # ---------- preparation ----------

    def _snapshot(self, campaign_id: str) -> SnapshotRef:
        """A dated photo of the inventory for a campaign, with what the shapes will validate.

        The coherence challenges answer from the data frozen here, never from the live graph: the
        same campaign always says the same (security review F09-02, SEC-036). Both are taken one
        after the other from the live graph, not in one transaction of AGE.
        """
        store = GraphStore(self._dsn)
        snapshot = take_snapshot(store, self._dsn, f"campaign-{campaign_id}")
        store_snapshot_data(self._dsn, snapshot.id, export_graph(store))
        return snapshot

    def _prepare(self, campaign_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(campaign_id)
        ontology_version = version_in_force(self._dsn)
        # What decides the verdicts is the signed bundle in force, on this disk and in OPA; a
        # changed challenge, policy or shape stops the campaign before it compiles (SEC-011).
        verify_on_disk(self._dsn, ontology_version, LIBRARY_DIR)
        verify_running_policies(
            self._dsn, ontology_version, loaded_policies(self._opa_url, token=self._opa_token)
        )
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
        injected = [
            row["system_id"] for row in injections(self._dsn, campaign_id) if not row["reverted"]
        ]
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
                "injected_systems": injected,
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

    @activity.defn(name="check_gate")
    async def check_gate(self, payload: dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            gate_is_open, self._dsn, str(payload["campaign_id"]), str(payload["gate"])
        )

    @activity.defn(name="set_campaign_status")
    async def set_campaign_status(self, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(
            set_status, self._dsn, str(payload["campaign_id"]), str(payload["status"])
        )

    def _reversions(self, campaign_id: str) -> dict[str, list[Any]]:
        """Whether the synthetic subject of a campaign is really gone from where it was injected.

        A confirmation of the client is not enough: for every reverted injection a read-only
        `count` looks for the markers of the subject in the columns of the injection point that
        can hold them (security review F09-02, SEC-015). An injection that cannot be looked at is
        reported as such, never taken as clean. Nothing is looked for until every injection is
        confirmed as reverted.
        """
        confirmed = injections(self._dsn, campaign_id)
        pending = [row["id"] for row in confirmed if not row["reverted"]]
        remaining: list[dict[str, str]] = []
        unverifiable: list[dict[str, str]] = []
        if pending or not confirmed:
            return {"pending": pending, "remaining": remaining, "unverifiable": unverifiable}
        subject = campaign_subject(self._dsn, campaign_id)
        snapshot_id = campaign_record(self._dsn, campaign_id).get("snapshot_id")
        nodes = snapshot_nodes(self._dsn, str(snapshot_id)) if snapshot_id else []
        systems = _registered_systems(self._dsn)
        for row in confirmed:
            system = systems.get(row["system_id"])
            connector = connector_id(system) if system is not None else None
            columns = [
                (str(node["qualified_name"]), REVERSION_MARKERS[str(category["category"])])
                for node in nodes
                if node["label"] == "Column"
                and str(node["system_id"]) == row["system_id"]
                and str(node["qualified_name"]).startswith(f"{row['point']}.")
                for category in node["categories"]
                if str(category.get("category")) in REVERSION_MARKERS
            ]
            where = {"injection": row["id"], "system_id": row["system_id"], "point": row["point"]}
            if subject is None or connector not in REVERSION_CONNECTORS or not columns:
                unverifiable.append({**where, "reason": "no column of the point can be probed"})
                continue
            for qualified_name, marker in sorted(set(columns)):
                spec = ProbeSpec(
                    kind="count",
                    target=row["point"],
                    statement=None,
                    params={
                        "filters": [
                            {
                                "column": qualified_name.rsplit(".", 1)[1],
                                "operator": "==",
                                "value": subject.markers[marker],
                                "cast": "text",
                            }
                        ]
                    },
                )
                result = run_probe(self._dsn, self._secrets, row["system_id"], spec)
                count = result.data.get("count")
                if not result.ok or count is None:
                    unverifiable.append({**where, "reason": f"{qualified_name} did not answer"})
                elif int(count) > 0:
                    remaining.append({**where, "column": qualified_name})
        return {"pending": pending, "remaining": remaining, "unverifiable": unverifiable}

    @activity.defn(name="check_reversions")
    async def check_reversions(self, campaign_id: str) -> dict[str, list[Any]]:
        return await asyncio.to_thread(self._reversions, campaign_id)

    def _seal(self, campaign_id: str) -> dict[str, Any]:
        check = self._reversions(campaign_id)
        if any(check.values()):
            raise ApplicationError(
                "the synthetic subject is not verified as reverted: the campaign is not sealed",
                check,
                type="ReversionNotVerified",
                non_retryable=True,
            )
        return seal_campaign(self._dsn, campaign_id)

    @activity.defn(name="seal_campaign")
    async def seal(self, campaign_id: str) -> dict[str, Any]:
        sealed = await asyncio.to_thread(self._seal, campaign_id)
        if self._bus is not None:
            await announce_seal(self._bus, sealed)
        return sealed

    # ---------- remediation ----------

    def _start_remediation(self, scope: Mapping[str, Any]) -> dict[str, Any]:
        """The units to re-run: exactly the ones that opened the findings awaiting verification.

        The unit is the one stored with the verdict, so the remediation is measured with the same
        challenge version that measured the problem, even if the library has moved on (ARG-049).
        """
        requested_by = str(scope.get("requested_by") or "")
        if not requested_by.startswith("user:"):
            # The gates keep who asked apart from who approves: nobody anonymous asks (SEC-010).
            raise ApplicationError(
                "a remediation run needs the person who asks for it",
                type="RequesterMissing",
                non_retryable=True,
            )
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
            requested_by,
        )
        # What the client fixed is measured on the inventory as it is now: a new snapshot, and
        # every unit points to it instead of the one that found the problem (SEC-036).
        snapshot = self._snapshot(campaign_id)
        pin_campaign(
            self._dsn,
            campaign_id,
            snapshot_id=snapshot.id,
            snapshot_hash=snapshot.content_hash,
            ontology_version=(origin or {}).get("ontology_version") or "0.0.0",
            library_version=(origin or {}).get("library_version") or "0.0.0",
            library_sha256=(origin or {}).get("library_sha256") or "0" * 64,
            applicability_run=None,
        )
        units: list[dict[str, Any]] = []
        measured_on: dict[str, Any] = {}
        for finding_id, unit in rows:
            work = dict(unit)
            original = str(work["campaign_id"])
            if original not in measured_on:
                measured_on[original] = campaign_record(self._dsn, original).get("snapshot_id")
            if measured_on[original]:
                work["probe"] = _with_snapshot(
                    work["probe"], str(measured_on[original]), snapshot.id
                )
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
            REMEDIATION_ACTOR,
        )

    # ---------- probes ----------

    def _internal_probe(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        probe = unit["probe"]
        kind = str(probe["kind"])
        params = dict(probe.get("params", {}))
        if kind == "shacl":
            snapshot_id = campaign_record(self._dsn, str(unit["campaign_id"])).get("snapshot_id")
            if not snapshot_id:
                raise ApplicationError(
                    "the campaign has no snapshot to validate",
                    type="NoSnapshot",
                    non_retryable=True,
                )
            data = snapshot_data(self._dsn, str(snapshot_id))
            findings = validate_graph(data, load_shapes())
            shape, severity = params.get("shape"), params.get("severity")
            scope = _system_scope(data, str(unit["system_id"]))
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
            "campaign_id": unit["campaign_id"],
        }
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(statement, arguments).fetchone()
        if row is None or row[0] is None:
            # A question ARGOS cannot answer is not a zero: the evaluator turns it into
            # `inconclusive` because the field is missing, never into `compliant`.
            return {"ok": True, "data": {}}
        return {"ok": True, "data": {"count": int(row[0])}}

    def _run_probe(
        self, unit: Mapping[str, Any], on_circuit_open: CircuitListener | None = None
    ) -> dict[str, Any]:
        if str(unit["probe"]["kind"]) in INTERNAL_PROBES:
            answer = self._internal_probe(unit)
            answer["data"] = minimise(answer["data"], unit["evidence"]["capture"])
            return answer
        try:
            result = run_probe(
                self._dsn,
                self._secrets,
                str(unit["system_id"]),
                probe_spec(unit),
                on_circuit_open,
            )
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
        # A slow system opens its circuit here; the campaigns asking it pause (ARG-013 → ARG-043).
        listener = (
            bus_circuit_listener(self._bus, asyncio.get_running_loop())
            if self._bus is not None
            else None
        )
        return await asyncio.to_thread(self._run_probe, unit, listener)

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

    def _planned(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        """The unit exactly as the campaign planned it, in a campaign that may be evaluated now.

        Whoever reaches Temporal can start a workflow with units of their own; only the evaluator
        writes verdicts, and it only writes them for the plan (security review F09-02, SEC-007).
        """
        campaign_id = str(unit["campaign_id"])
        planned = stored_unit(self._dsn, campaign_id, str(unit["unit_id"]))
        if planned is None or _canonical(planned) != _canonical(unit):
            raise ApplicationError(
                "the unit is not the one in the campaign plan",
                type="UnitNotPlanned",
                non_retryable=True,
            )
        if campaign_record(self._dsn, campaign_id)["status"] != "running":
            raise ApplicationError(
                "the campaign is not running", type="CampaignNotRunning", non_retryable=True
            )
        gates = ["start", "sampling"] if planned.get("needs_approval") else ["start"]
        closed = [g for g in gates if not gate_is_open(self._dsn, campaign_id, g)]
        if closed:
            raise ApplicationError(
                f"the gate(s) {', '.join(closed)} are not approved",
                type="GateNotOpen",
                non_retryable=True,
            )
        return planned

    def _decide(self, unit: Mapping[str, Any], probe_result: Mapping[str, Any]) -> dict[str, Any]:
        unit = self._planned(unit)
        criterion = unit.get("criterion", {})
        decision: dict[str, Any] | None = None
        opa_input: dict[str, Any] | None = None
        if "opa" in criterion and probe_result.get("ok"):
            package = str(criterion["opa"]["package"])
            # The evidence is always the probe's: what a challenge declares never overrides it.
            declared = dict(criterion["opa"].get("input_map", {}))
            opa_input = {k: v for k, v in declared.items() if k not in EVIDENCE_INPUT_KEYS}
            opa_input["result"] = probe_result.get("data", {})
            try:
                decision = opa_evaluate(package, opa_input, self._opa_url, token=self._opa_token)
            except OpaError as exc:
                # An outage is not an answer: retry, never freeze it as `inconclusive` (SEC-037).
                raise ApplicationError(str(exc), type="OpaUnavailable") from exc
        verdict = evaluate(unit, probe_result, decision, opa_input=opa_input)
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
