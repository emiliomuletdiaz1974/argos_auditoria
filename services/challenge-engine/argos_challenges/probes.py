"""Probe execution and minimisation for a work unit (ARG-044).

Two families of probe:
- the connector ones (`scan_schema`, `count`, `sample`, `check_config`) run through the SDK, which
  already brings the previous journal entry, the load budget and the read-only guarantee;
- the internal ones (`shacl`, `inventory_query`) read what ARGOS already knows about the
  client — the pinned snapshot and the graph — and never touch a client system.

Whatever comes back is **cut down to what the challenge declared to capture** before it goes any
further: the minimisation happens here, so nothing undeclared reaches the workflow history.
"""

from collections.abc import Mapping
from typing import Any

from argos_connector.probes import ProbeSpec

# What each declared capture lets through, by key of the probe result.
CAPTURE_KEYS: Mapping[str, tuple[str, ...]] = {
    "result": ("ok", "kind"),
    "counts": ("count", "n", "total", "rows_touched"),
    "hashes": ("cell_digests", "head_sha256", "dns_sha256", "digests"),
    "configuration": ("rows", "schemas", "security_headers", "acl", "settings"),
    "hashed_sample": ("columns", "n", "cell_digests", "validator_rates", "validated"),
}
# Read-only questions ARGOS answers about itself, by name. A challenge cannot write its own query.
# Every one of them answers with a single value: no row means ARGOS cannot answer, not zero.
INVENTORY_QUERIES: Mapping[str, str] = {
    "unclassified_columns": (
        "SELECT count(*) AS count FROM argos.inventory_snapshot_nodes "
        "WHERE snapshot_id = %(snapshot_id)s AND label = 'Column' "
        "AND system_id = %(system_id)s AND categories = '[]'::jsonb"
    ),
    "pending_ai_systems": (
        "SELECT count(*) AS count FROM argos.inventory_snapshot_nodes "
        "WHERE snapshot_id = %(snapshot_id)s AND label = 'AISystem' "
        "AND system_id = %(system_id)s AND coalesce(status, '') <> 'confirmed'"
    ),
    # The term the client declares, from the request to the answer, for this campaign's subject
    # only; the slowest answer when there are several (security review F09-02, SEC-014).
    "access_request_days": (
        "SELECT EXTRACT(DAY FROM e.answered_at - e.requested_at)::int AS days "
        "FROM argos.synthetic_exercises e "
        "JOIN argos.synthetic_injections i ON i.id = e.injection_id "
        "JOIN argos.synthetic_subjects s ON s.id = i.subject_id "
        "WHERE i.system_id = %(system_id)s AND s.campaign_id = %(campaign_id)s "
        "AND e.exercised_right = 'access' "
        "ORDER BY e.answered_at - e.requested_at DESC LIMIT 1"
    ),
    "prohibited_ai_systems": (
        "SELECT count(*) AS count FROM argos.inventory_snapshot_nodes "
        "WHERE snapshot_id = %(snapshot_id)s AND label = 'AISystem' "
        "AND system_id = %(system_id)s AND status = 'prohibited'"
    ),
}


def minimise(data: Mapping[str, Any], capture: Mapping[str, Any] | list[str]) -> dict[str, Any]:
    """Only the keys the declared captures allow; anything else never leaves the probe."""
    names = list(capture) if not isinstance(capture, Mapping) else list(capture.get("capture", []))
    allowed = {key for name in names for key in CAPTURE_KEYS.get(str(name), ())}
    return {key: value for key, value in data.items() if key in allowed}


def probe_spec(unit: Mapping[str, Any]) -> ProbeSpec:
    probe = unit["probe"]
    return ProbeSpec(
        kind=str(probe["kind"]),
        target=str(probe["target"]),
        statement=probe.get("statement"),
        params=dict(probe.get("params", {})),
    )
