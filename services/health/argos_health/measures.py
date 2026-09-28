"""Each measure of the domain health, as a function over its source (ARG-094, F10-02).

The journal and the security log are verified with their own verifiers, never with a chain
re-implemented here. The states are the real ones of the tables: a campaign is `pinned` or
`running`, a time-stamp request `queued`, a delivery `pending` or `retrying`, a proposal of the
review queue `pending`, a circuit `open`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import psycopg

from argos_common.journal_pg import PostgresJournal
from argos_common.security_log import verify_chain

CANARY_PREFIX = "health/canary/"
CANARY_RETENTION = dt.timedelta(days=1)
CERT_WINDOW = dt.timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Observation:
    name: str
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)
    help: str = ""


class WormLike(Protocol):
    def put_immutable(self, key: str, data: bytes, retain_until: dt.datetime) -> Any: ...

    def get(self, key: str, version_id: str | None = None) -> bytes: ...


# ---------- pure ----------


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def render_metrics(observations: Iterable[Observation]) -> str:
    """Prometheus text format: one HELP and TYPE per metric, then its samples."""
    by_name: dict[str, list[Observation]] = {}
    for observation in observations:
        by_name.setdefault(observation.name, []).append(observation)
    lines: list[str] = []
    for name, samples in by_name.items():
        text = next((s.help for s in samples if s.help), name)
        lines += [f"# HELP {name} {text}", f"# TYPE {name} gauge"]
        for sample in samples:
            labels = ",".join(f'{k}="{_label(v)}"' for k, v in sorted(sample.labels.items()))
            lines.append(
                f"{name}{{{labels}}} {_number(sample.value)}"
                if labels
                else f"{name} {_number(sample.value)}"
            )
    return "\n".join(lines) + "\n"


def journal_tail_start(head: int, tail: int) -> int:
    """The first sequence of the last `tail` entries of a journal whose head is `head`."""
    return max(1, head - tail + 1)


def certificates_expiring(
    certificates: Iterable[Mapping[str, Any]],
    now: dt.datetime,
    window: dt.timedelta = CERT_WINDOW,
    expected: Collection[str] | None = None,
) -> list[str]:
    """The names whose newest certificate expires within the window.

    The issuer renews at two thirds of the life of a certificate, so the old one still exists and
    expires soon after the service already uses the new one: only the newest of each name counts.
    With `expected` (the services the issuer renews), a retired name no longer counts, and an
    expected service without any certificate does (quality review QA-088).
    """
    newest: dict[str, dt.datetime] = {}
    for certificate in certificates:
        name, not_after = str(certificate["common_name"]), certificate["not_after"]
        if expected is not None and name not in expected:
            continue
        if name not in newest or not_after > newest[name]:
            newest[name] = not_after
    expiring = {name for name, not_after in newest.items() if not_after - now < window}
    if expected is not None:
        expiring |= set(expected) - set(newest)
    return sorted(expiring)


def worm_canary(store: WormLike, now: dt.datetime) -> bool:
    """Write a small object with retention, read it back and compare. Never raises."""
    payload = f"argos-health-canary {now.isoformat()}".encode()
    key = f"{CANARY_PREFIX}{now.strftime('%Y%m%dT%H%M%S.%fZ')}"
    try:
        store.put_immutable(key, payload, now + CANARY_RETENTION)
        back = store.get(key)
    except Exception:  # an unreachable or failing store is exactly what the canary reports
        return False
    return hashlib.sha256(back).digest() == hashlib.sha256(payload).digest()


def volume_used_ratio(path: Path | None) -> float | None:
    """How full the evidence volume is; None when it is not visible from here."""
    if path is None or not path.exists():
        return None
    usage = shutil.disk_usage(path)
    return usage.used / usage.total if usage.total else None


# ---------- over the database ----------


def security_log_ok(dsn: str) -> bool:
    """The security log verifies its own chain, columns included (F09-08)."""
    return verify_chain(dsn).intact


def journal_ok(dsn: str, tail: int | None) -> bool:
    """The journal v1 verifies: its last `tail` entries, or all of it when `tail` is None."""
    journal = PostgresJournal(dsn)
    head, _ = journal.head()
    start = 1 if tail is None else journal_tail_start(head, tail)
    return journal.verify(from_seq=start).intact


_COUNTS = {
    "argos_campaigns_running": (
        "SELECT count(*) FROM argos.campaigns WHERE status IN ('pinned', 'running')",
        "Campaigns under way (pinned or running).",
    ),
    "argos_tsa_queue_pending": (
        "SELECT count(*) FROM argos.tsa_queue WHERE status = 'queued'",
        "Time-stamp requests waiting for their token.",
    ),
    "argos_webhook_deliveries_pending": (
        "SELECT count(*) FROM argos.webhook_deliveries WHERE status IN ('pending', 'retrying')",
        "Webhook deliveries not yet delivered.",
    ),
    "argos_review_queue_pending": (
        "SELECT count(*) FROM argos.review_queue WHERE status = 'pending'",
        "Classification proposals waiting for a person.",
    ),
}
# A queue is stalled when something waits in it for more than a day.
_STALLED = (
    "SELECT (SELECT count(*) FROM argos.tsa_queue"
    "         WHERE status = 'queued' AND enqueued_at < now() - interval '1 day')"
    "     + (SELECT count(*) FROM argos.webhook_deliveries"
    "         WHERE status IN ('pending', 'retrying') AND created_at < now() - interval '1 day')"
)
# A gate is waiting while the campaign asked for it and nobody approved it yet.
_GATES = (
    "SELECT r.campaign_id::text, r.gate, extract(epoch FROM now() - r.requested_at) / 3600"
    "  FROM argos.approval_requests r JOIN argos.campaigns c ON c.id = r.campaign_id"
    " WHERE c.status NOT IN ('sealed', 'failed')"
    "   AND NOT EXISTS (SELECT 1 FROM argos.approvals a"
    "                    WHERE a.campaign_id = r.campaign_id AND a.gate = r.gate)"
)
_CIRCUITS = (
    "SELECT s.name, CASE WHEN b.state = 'open' THEN 1 ELSE 0 END"
    "  FROM argos.load_budget b JOIN argos.systems s ON s.id::text = b.system_id"
)
_SCANS = (
    "SELECT DISTINCT ON (r.system_id) s.name, extract(epoch FROM r.finished_at - r.started_at)"
    "  FROM argos.scan_runs r JOIN argos.systems s ON s.id = r.system_id"
    " WHERE r.status = 'completed' AND r.finished_at IS NOT NULL"
    " ORDER BY r.system_id, r.finished_at DESC"
)
# F10-04 (ARG-092): what the compliance and AI dashboards show.
SEVERITIES = ("critical", "high", "medium", "low")
CAMPAIGN_STATUSES = ("planned", "pinned", "running", "sealed", "failed")
_FINDINGS_OPEN = (
    "SELECT severity, count(*) FROM argos.findings"
    " WHERE status IN ('open', 'in_remediation', 'pending_verification', 'reopened')"
    " GROUP BY severity"
)
# How long a finding took to be verified as remedied, over the last 90 days (median, hours).
_REMEDIATION = (
    "SELECT percentile_cont(0.5) WITHIN GROUP"
    " (ORDER BY extract(epoch FROM updated_at - created_at) / 3600)"
    "  FROM argos.findings"
    " WHERE status = 'closed_compliant' AND updated_at > now() - interval '90 days'"
)
_CAMPAIGNS = "SELECT status, count(*) FROM argos.campaigns GROUP BY status"
_COVERAGE = "SELECT system_name, coverage_pct / 100.0 FROM argos.catalog_coverage"
_AI_USAGE = (
    "SELECT u.service, sum(u.tokens_in + u.tokens_out), count(*),"
    "       percentile_disc(0.95) WITHIN GROUP (ORDER BY u.duration_ms),"
    "       max(q.daily_tokens)"
    "  FROM argos.ai_usage u LEFT JOIN argos.ai_quotas q ON q.service = u.service"
    " WHERE u.created_at > now() - interval '24 hours'"
    " GROUP BY u.service"
)
_CALIBRATION = (
    "SELECT category, extract(epoch FROM now() - fitted_at) / 3600 FROM argos.ai_calibration"
)
_JOBS = {
    "backup": "SELECT max(at) FROM argos.audit_journal WHERE action = 'backup.completed'",
    "restore_test": "SELECT max(tested_at) FROM argos.restore_tests WHERE result = 'passed'",
    "calibration": "SELECT max(fitted_at) FROM argos.ai_calibration",
    "rescan": "SELECT max(finished_at) FROM argos.scan_runs WHERE status = 'completed'",
}


def domain_observations(dsn: str) -> tuple[list[Observation], int]:
    """Campaigns, queues, gates, circuits and jobs; and how many queue items are stalled."""
    found: list[Observation] = []
    with psycopg.connect(dsn) as conn:
        for name, (query, text) in _COUNTS.items():
            row = conn.execute(query).fetchone()
            found.append(Observation(name, float(row[0] if row else 0), help=text))
        stalled_row = conn.execute(_STALLED).fetchone()
        for campaign, gate, hours in conn.execute(_GATES).fetchall():
            found.append(
                Observation(
                    "argos_campaign_gate_waiting_hours",
                    round(float(hours), 2),
                    {"campaign": str(campaign), "gate": str(gate)},
                    help="Hours a campaign has waited at a gate nobody approved.",
                )
            )
        for system, is_open in conn.execute(_CIRCUITS).fetchall():
            found.append(
                Observation(
                    "argos_connector_circuit_open",
                    float(is_open),
                    {"system": str(system)},
                    help="Whether the circuit breaker of a system is open.",
                )
            )
        for system, seconds in conn.execute(_SCANS).fetchall():
            found.append(
                Observation(
                    "argos_scan_last_duration_seconds",
                    round(float(seconds), 1),
                    {"system": str(system)},
                    help="How long the last completed scan of each system took.",
                )
            )
        for job, query in _JOBS.items():
            row = conn.execute(query).fetchone()
            at = row[0] if row else None
            found.append(
                Observation(
                    "argos_job_last_success_timestamp_seconds",
                    float(at.timestamp()) if at is not None else 0.0,
                    {"job": job},
                    help="When a periodic job last succeeded (0: never).",
                )
            )
        found += _compliance(conn) + _ai(conn)
    return found, int(stalled_row[0] if stalled_row else 0)


def _compliance(conn: psycopg.Connection[Any]) -> list[Observation]:
    found: list[Observation] = []
    open_by = {str(s): int(n) for s, n in conn.execute(_FINDINGS_OPEN).fetchall()}
    # Every severity, even at zero: a dashboard that reads "no data" hides a healthy state.
    for severity in SEVERITIES:
        found.append(
            Observation(
                "argos_findings_open",
                float(open_by.get(severity, 0)),
                {"severity": severity},
                help="Findings not yet closed, by severity.",
            )
        )
    row = conn.execute(_REMEDIATION).fetchone()
    if row is not None and row[0] is not None:
        found.append(
            Observation(
                "argos_findings_remediation_hours",
                round(float(row[0]), 1),
                help="Median hours from a finding to its verified remediation (last 90 days).",
            )
        )
    by_status = {str(s): int(n) for s, n in conn.execute(_CAMPAIGNS).fetchall()}
    for status in CAMPAIGN_STATUSES:
        found.append(
            Observation(
                "argos_campaigns_total",
                float(by_status.get(status, 0)),
                {"status": status},
                help="Campaigns by status.",
            )
        )
    for system, ratio in conn.execute(_COVERAGE).fetchall():
        if ratio is None:
            continue
        found.append(
            Observation(
                "argos_inventory_coverage_ratio",
                round(float(ratio), 4),
                {"system": str(system)},
                help="Share of the columns of a system with a category (0 to 1).",
            )
        )
    return found


def _ai(conn: psycopg.Connection[Any]) -> list[Observation]:
    found: list[Observation] = []
    for service, tokens, requests, p95, quota in conn.execute(_AI_USAGE).fetchall():
        labels = {"service": str(service)}
        found += [
            Observation(
                "argos_ai_tokens_24h", float(tokens), labels, help="AI tokens in the last 24 hours."
            ),
            Observation(
                "argos_ai_requests_24h",
                float(requests),
                labels,
                help="AI requests in the last 24 hours.",
            ),
            Observation(
                "argos_ai_latency_p95_ms",
                float(p95),
                labels,
                help="95th percentile of the AI request duration in the last 24 hours.",
            ),
        ]
        if quota:
            found.append(
                Observation(
                    "argos_ai_quota_used_ratio",
                    round(float(tokens) / float(quota), 4),
                    labels,
                    help="Share of the daily token quota used in the last 24 hours.",
                )
            )
    for category, hours in conn.execute(_CALIBRATION).fetchall():
        found.append(
            Observation(
                "argos_ai_calibration_age_hours",
                round(float(hours), 1),
                {"category": str(category)},
                help="Hours since the confidence curve of a category was fitted.",
            )
        )
    return found


def publish_facts(dsn: str, facts: Mapping[str, tuple[str, dt.datetime]]) -> None:
    """What the self-* challenges read through `argos_facts.facts` (F10-01).

    Each fact carries the time of the check that observed it: a check that hangs leaves its fact
    growing old, and `argos_facts.fresh` stops trusting it (quality review QA-078).
    """
    with psycopg.connect(dsn) as conn:
        for fact, (setting, at) in sorted(facts.items()):
            conn.execute(
                "INSERT INTO argos.health_facts (fact, setting, observed_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (fact) DO UPDATE SET setting = EXCLUDED.setting,"
                " observed_at = EXCLUDED.observed_at",
                (fact, setting, at),
            )


def as_facts(observations: Sequence[Observation], stalled: int) -> dict[str, str]:
    """The observations as the facts the self-* challenges and `/facts` answer.

    The journal is intact when every verification that ran passed (the tail and, once a day, the
    whole chain), and at least one ran: nothing verified is not intact.
    """
    single = {o.name: o.value for o in observations if not o.labels}
    journal = [o.value for o in observations if o.name == "argos_journal_verify_ok"]
    return {
        "journal_intact": "1" if journal and all(v == 1 for v in journal) else "0",
        "security_log_intact": str(int(single.get("argos_security_log_verify_ok", 0))),
        "worm_healthy": str(int(single.get("argos_worm_healthy", 0))),
        "certs_expiring_7d": str(int(single.get("argos_certs_expiring_7d", -1))),
        "queues_stalled": str(stalled),
    }
