"""ARG-092/099 · what the operation screen shows: the eight lights and the alerts (F10-07).

The lights are the same eight expressions of the operation dashboard (F10-04), asked to Prometheus
when the screen asks. A light nobody measures is `unknown`, never green: the operator must see that
the appliance is blind there. The alerts are the ones Alertmanager delivered to the API, each with
the runbook its rule names (F10-06).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True, slots=True)
class Light:
    key: str
    title: str
    expr: str
    healthy: Callable[[float], bool]


# The eight lights of the operation dashboard, in its order.
LIGHTS: tuple[Light, ...] = (
    Light("journal", "Diario", "min(argos_journal_verify_ok)", lambda v: v >= 1),
    Light("worm", "Almacén WORM", "argos_worm_healthy", lambda v: v >= 1),
    Light("services", "Servicios", 'min(up{job=~"argos-.*"})', lambda v: v >= 1),
    Light("tsa", "Cola de sellado", "argos_tsa_queue_pending", lambda v: v <= 50),
    Light("backup", "Copias", "argos_backup_last_restore_test_success", lambda v: v >= 1),
    Light(
        "evidence_disk",
        "Disco de evidencia",
        "argos_evidence_volume_used_ratio",
        lambda v: v < 0.85,
    ),  # fmt: skip
    Light("certificates", "Certificados", "argos_certs_expiring_7d", lambda v: v == 0),
    Light("version", "Versión", "argos_build_info", lambda v: True),
)
# ASCII digits and nothing after the name: `\d` takes other digits and `$` a final newline, which
# the CHECK of the table refuses (quality review QA-060).
RUNBOOK_ID = re.compile(r"\ARB-[0-9]{2}-[a-z0-9-]+\Z")


class Metrics(Protocol):
    def query(self, expr: str) -> float | None: ...


class PrometheusMetrics:
    """The value of an instant query, or None when it has no sample or Prometheus does not answer.

    For `argos_build_info` the value is the version label: the only light that is a text.
    """

    def __init__(self, url: str, timeout: float = 3.0) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self.labels: dict[str, str] = {}

    def _result(self, expr: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"query": expr})
        url = f"{self._url}/api/v1/query?{query}"
        with urllib.request.urlopen(url, timeout=self._timeout) as response:  # noqa: S310
            body = json.loads(response.read())
        return list(body.get("data", {}).get("result", []))

    def query(self, expr: str) -> float | None:
        try:
            result = self._result(expr)
        except (OSError, ValueError):
            return None
        if not result:
            return None
        self.labels[expr] = str(result[0].get("metric", {}).get("version", ""))
        return float(result[0]["value"][1])


def lights(metrics: Metrics) -> list[dict[str, Any]]:
    found = []
    for light in LIGHTS:
        value = metrics.query(light.expr)
        state = "unknown" if value is None else ("green" if light.healthy(value) else "red")
        entry: dict[str, Any] = {"key": light.key, "title": light.title, "state": state,
                                 "value": value}  # fmt: skip
        if light.key == "version":
            labels = getattr(metrics, "labels", {})
            entry["text"] = labels.get(light.expr) or None
        found.append(entry)
    return found


def _runbook(url: str | None) -> str | None:
    if not url:
        return None
    name = Path(url).stem
    return name if RUNBOOK_ID.match(name) else None


def _instant(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text or text.startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class MalformedNotificationError(ValueError):
    """What arrived is not a notification of Alertmanager."""


class Alerts(Protocol):
    def receive(self, notification: Mapping[str, Any]) -> int: ...

    def active(self) -> list[dict[str, Any]]: ...


def _rows(notification: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """The alerts that can be kept. One malformed alert is skipped, not the batch (QA-060)."""
    alerts = notification.get("alerts", [])
    if not isinstance(alerts, list):
        raise MalformedNotificationError("alerts is not a list")
    for alert in alerts:
        if not isinstance(alert, Mapping) or not alert.get("fingerprint"):
            continue
        labels = alert.get("labels")
        labels = dict(labels) if isinstance(labels, Mapping) else {}
        annotations = alert.get("annotations")
        annotations = dict(annotations) if isinstance(annotations, Mapping) else {}
        runbook_url = annotations.get("runbook_url")
        yield {
            "fingerprint": str(alert["fingerprint"])[:64],
            "alertname": str(labels.get("alertname", ""))[:120],
            "severity": str(labels.get("severity", ""))[:20],
            "status": "firing" if alert.get("status") == "firing" else "resolved",
            "summary": str(annotations.get("summary", ""))[:500],
            "runbook": _runbook(runbook_url if isinstance(runbook_url, str) else None),
            "labels": {str(k)[:60]: str(v)[:200] for k, v in labels.items()},
            "starts_at": _instant(alert.get("startsAt")),
        }


class MemoryAlerts:
    """The alerts in memory: for the tests and an API without a database."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def receive(self, notification: Mapping[str, Any]) -> int:
        count = 0
        for row in _rows(notification):
            if not _late(self._rows.get(row["fingerprint"]), row):
                self._rows[row["fingerprint"]] = row
            count += 1
        return count

    def active(self) -> list[dict[str, Any]]:
        return _public(r for r in self._rows.values() if r["status"] == "firing")


def _late(stored: Mapping[str, Any] | None, row: Mapping[str, Any]) -> bool:
    """A `firing` of an episode already resolved, delivered late: it must not revive it. A new
    episode has a later start (quality review QA-066)."""
    if stored is None or stored["status"] != "resolved" or row["status"] != "firing":
        return False
    before, now = stored["starts_at"], row["starts_at"]
    return before is None or now is None or now <= before


def _public(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: (r["severity"] != "critical", r["alertname"]))
    return [
        {
            "alertname": r["alertname"],
            "severity": r["severity"],
            "summary": r["summary"],
            "runbook": r["runbook"],
            "labels": r["labels"],
            "starts_at": r["starts_at"].isoformat() if r["starts_at"] else None,
        }
        for r in ordered
    ]


class PostgresAlerts:
    """The alerts in `argos.operation_alerts`, shared by every replica of the API."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def receive(self, notification: Mapping[str, Any]) -> int:
        count = 0
        now = datetime.now(UTC)
        with psycopg.connect(self._dsn) as conn:
            for row in _rows(notification):
                conn.execute(
                    "INSERT INTO argos.operation_alerts (fingerprint, alertname, severity, status,"
                    " summary, runbook, labels, starts_at, updated_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (fingerprint) DO UPDATE SET status = EXCLUDED.status,"
                    " summary = EXCLUDED.summary, runbook = EXCLUDED.runbook,"
                    " labels = EXCLUDED.labels, updated_at = EXCLUDED.updated_at,"
                    " starts_at = coalesce(EXCLUDED.starts_at, argos.operation_alerts.starts_at)"
                    # A late firing of a resolved episode does not revive it (QA-066).
                    " WHERE NOT (argos.operation_alerts.status = 'resolved'"
                    " AND EXCLUDED.status = 'firing' AND (EXCLUDED.starts_at IS NULL"
                    " OR argos.operation_alerts.starts_at IS NULL"
                    " OR EXCLUDED.starts_at <= argos.operation_alerts.starts_at))",
                    (
                        row["fingerprint"], row["alertname"], row["severity"], row["status"],
                        row["summary"], row["runbook"], Jsonb(row["labels"]), row["starts_at"],
                        now,
                    ),
                )  # fmt: skip
                count += 1
        return count

    def active(self) -> list[dict[str, Any]]:
        with psycopg.connect(self._dsn) as conn:
            cursor = conn.execute(
                "SELECT fingerprint, alertname, severity, status, summary, runbook, labels,"
                " starts_at FROM argos.operation_alerts WHERE status = 'firing'"
            )
            names = [c.name for c in cursor.description or []]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        return _public(rows)


def runbook_text(folder: Path, runbook_id: str) -> str | None:
    """The markdown of a runbook, without its header; None for anything that is not one."""
    if not RUNBOOK_ID.match(runbook_id):
        return None
    path = folder / f"{runbook_id}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").split("---\n", 2)[-1].lstrip()
