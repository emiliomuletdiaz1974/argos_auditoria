"""Campaign compiler: applicability plan plus library gives inert work units (ARG-042).

Between the declared challenge and the probe there are three resolutions: the nodes (already
resolved by the applicability run over the pinned snapshot), the probe variant (the same retention
challenge is probed differently in PostgreSQL and in an SMB share) and the parameters. The compiler
does all three **before** running anything, so the plan can be read by the DPO exactly as it will be
executed: the workflow interprets nothing.

Parameters are typed references (`{"$node": …}`, `{"$client": …}`, `{"$campaign": …}`,
`{"$subject": …}`) resolved to values here and passed as probe parameters; no value from
the graph is ever formatted into a statement. A challenge without a variant for a connector
does not disappear in silence: it becomes an `unverifiable` entry with its reason.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from argos_challenges.dsl import ChallengeSpec
from argos_common.errors import ArgosError

# The connector registered for a system decides which probe variant applies. The concrete engine of
# the generic SQL connector lives in its Vault secret, so its identifier stays generic.
CONNECTOR_IDS: Mapping[str, str] = {
    "argos_sql.postgres:PostgresConnector": "rdbms.postgresql",
    "argos_sql.mssql:MssqlConnector": "rdbms.mssql",
    "argos_sql.oracle:OracleConnector": "rdbms.oracle",
    "argos_sql.generic:SqlConnector": "rdbms.generic",
    "argos_files.connector:FilesConnector": "files",
    "argos_ldap.connector:LdapConnector": "directory.ldap",
    "argos_rest.connector:RestConnector": "api.rest",
    "argos_fhir.connector:FhirConnector": "clinical.fhir",
    "argos_dicom.connector:DicomConnector": "clinical.dicom",
}
REFERENCES = ("$node", "$client", "$campaign", "$subject")
# Derived from the qualified name of a node, because a count is run on a table, not on a column.
DERIVED_NODE_FIELDS = ("table", "column")
INTERNAL_PROBES = frozenset({"shacl", "inventory_query"})
INTERNAL_CONNECTOR = "argos.internal"


class CompilerError(ArgosError):
    """The campaign cannot be compiled: the plan, the library or the context does not fit."""


class MissingReferenceError(CompilerError):
    """A typed reference the campaign context cannot resolve, such as a subject that was not
    injected or a parameter the client has not declared. It does not break the campaign: the
    unit becomes `unverifiable` with its reason, like a challenge without a variant."""


@dataclass(frozen=True, slots=True)
class CompiledCampaign:
    units: list[dict[str, Any]] = field(default_factory=list)
    unverifiable: list[dict[str, Any]] = field(default_factory=list)


def unit_id(campaign_id: str, challenge_id: str, version: str, node_key: str) -> str:
    material = f"{campaign_id}|{challenge_id}|{version}|{node_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def connector_id(system: Mapping[str, Any]) -> str:
    """The identifier of the connector of a system, as challenges name it in `by_connector`."""
    base = CONNECTOR_IDS.get(str(system.get("connector")))
    if base is None:
        raise CompilerError(f"unknown connector: {system.get('connector')!r}")
    protocol = (system.get("config") or {}).get("protocol")
    return f"{base}.{protocol}" if base == "files" and protocol else base


def node_properties(node: Mapping[str, Any]) -> dict[str, Any]:
    """The properties a challenge can reference, with `table` and `column` derived."""
    properties = dict(node)
    qualified = str(node.get("qualified_name") or "")
    if str(node.get("label")) == "Column" and "." in qualified:
        table, _, column = qualified.rpartition(".")
        properties.setdefault("table", table)
        properties.setdefault("column", column)
    return properties


def _resolve(value: Any, node: Mapping[str, Any], context: Mapping[str, Any], where: str) -> Any:
    """Resolve typed references to values; anything else travels as it is."""
    if isinstance(value, Mapping):
        keys = set(value)
        if len(keys) == 1 and keys <= set(REFERENCES):
            [reference] = keys
            name = str(value[reference])
            source = node if reference == "$node" else (context.get(reference[1:]) or {})
            if name not in source or source[name] is None:
                raise MissingReferenceError(f"{where}: {reference} {name} is not available")
            return source[name]
        return {k: _resolve(v, node, context, where) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item, node, context, where) for item in value]
    return value


def _variant(spec: ChallengeSpec, connector: str) -> dict[str, Any] | None:
    if spec.probe_kind in INTERNAL_PROBES:
        return {"params": dict(spec.params)}
    if spec.by_connector:
        variant = spec.by_connector.get(connector)
        return None if variant is None else dict(variant)
    return {"params": dict(spec.params)}


def _unit(
    campaign_id: str,
    spec: ChallengeSpec,
    obligation: str,
    node: Mapping[str, Any],
    system: Mapping[str, Any],
    variant: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    node_key = str(node["node_key"])
    where = f"{spec.id} on {node_key}"
    properties = node_properties(node)
    if spec.probe_target is not None:
        target = _resolve(spec.probe_target, properties, context, where)
    else:
        target = properties.get("qualified_name") or properties.get("name")
    if not target:
        raise CompilerError(f"{where}: $node qualified_name is not available")
    probe = {
        "kind": spec.probe_kind,
        "target": str(target),
        "statement": variant.get("statement"),
        "params": _resolve(dict(variant.get("params", {})), properties, context, where),
    }
    return {
        "unit_id": unit_id(campaign_id, spec.id, spec.version, node_key),
        "campaign_id": campaign_id,
        "challenge_id": spec.id,
        "challenge_version": spec.version,
        "obligation": obligation,
        "system_id": str(system["id"]),
        "node_key": node_key,
        "probe": probe,
        "criterion": _criterion(spec, properties, context, where),
        "evidence": {"capture": list(spec.capture), "minimisation": spec.minimisation},
        "severity": spec.severity,
        "sampling": dict(spec.sampling) if spec.sampling else None,
        # Sampling decides what is not looked at: it always takes the double control, whatever
        # the challenge says (security review F09-02, SEC-009).
        "needs_approval": bool(
            spec.approval_required or spec.sampling or spec.probe_kind == "sample"
        ),
        "preconditions": list(spec.preconditions),
    }


def _criterion(
    spec: ChallengeSpec, properties: Mapping[str, Any], context: Mapping[str, Any], where: str
) -> dict[str, Any]:
    """The criterion with the references of its OPA input resolved, as for the probe (SEC-012)."""
    criterion = dict(spec.criterion)
    opa = criterion.get("opa")
    if isinstance(opa, Mapping) and opa.get("input_map"):
        criterion["opa"] = {
            **opa,
            "input_map": _resolve(dict(opa["input_map"]), properties, context, where),
        }
    return criterion


def compile_campaign(
    campaign_id: str,
    plan: Sequence[Mapping[str, Any]],
    challenges: Mapping[str, ChallengeSpec],
    nodes: Mapping[str, Mapping[str, Any]],
    systems: Mapping[str, Mapping[str, Any]],
    context: Mapping[str, Any] | None = None,
    reserved: frozenset[str] = frozenset(),
) -> CompiledCampaign:
    """Work units for the campaign, sorted by system and unit, and what cannot be verified."""
    resolved_context = dict(context or {})
    units: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []
    for row in plan:
        challenge_id = str(row["challenge_id"])
        spec = challenges.get(challenge_id)
        if spec is None:
            if challenge_id not in reserved:
                raise CompilerError(f"unknown challenge in the plan: {challenge_id}")
            # The obligation cites an id the library has reserved but not written yet: honest about
            # it, one entry per node, instead of pretending the obligation is verified.
            unverifiable.extend(
                {
                    "challenge_id": challenge_id,
                    "connector": None,
                    "node_key": str(node_key),
                    "reason": "the challenge is reserved in the catalog but not written yet",
                    "system_id": str((nodes.get(str(node_key)) or {}).get("system_id", "")),
                }
                for node_key in row["node_keys"]
            )
            continue
        obligation = str(row["obligation"])
        for raw_key in row["node_keys"]:
            node_key = str(raw_key)
            node = nodes.get(node_key)
            if node is None:
                raise CompilerError(f"unknown node in the plan: {node_key}")
            system = systems.get(str(node["system_id"]))
            if system is None:
                raise CompilerError(f"unknown system for the node {node_key}")
            connector = (
                INTERNAL_CONNECTOR if spec.probe_kind in INTERNAL_PROBES else connector_id(system)
            )
            variant = _variant(spec, connector)
            if variant is None:
                unverifiable.append(
                    {
                        "challenge_id": challenge_id,
                        "connector": connector,
                        "node_key": node_key,
                        "reason": "the challenge has no probe variant for this connector",
                        "system_id": str(system["id"]),
                    }
                )
                continue
            try:
                units.append(
                    _unit(campaign_id, spec, obligation, node, system, variant, resolved_context)
                )
            except MissingReferenceError as missing:
                unverifiable.append(
                    {
                        "challenge_id": challenge_id,
                        "connector": connector,
                        "node_key": node_key,
                        "reason": str(missing),
                        "system_id": str(system["id"]),
                    }
                )
    units.sort(key=lambda unit: (unit["system_id"], unit["unit_id"]))
    unverifiable.sort(key=lambda row: (row["challenge_id"], row["node_key"]))
    return CompiledCampaign(units, unverifiable)
