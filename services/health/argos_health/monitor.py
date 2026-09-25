"""The monitor: what the health service measures, how often, and what it keeps (ARG-094).

Each check replaces its own observations when it runs; a check that fails leaves its gauge at 0
and logs why, so a broken source shows up as an unhealthy value, never as a stale healthy one.
The facts that only this service observes go to `argos.health_facts`, where the self-* challenges
read them (F10-01).
"""

from __future__ import annotations

import datetime as dt
import json
import ssl
import threading
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.x509.oid import NameOID

from argos_common.logs import get_logger, loki_dropped

from .measures import (
    Observation,
    WormLike,
    as_facts,
    certificates_expiring,
    domain_observations,
    journal_ok,
    publish_facts,
    security_log_ok,
    volume_used_ratio,
    worm_canary,
)

Certificates = Callable[[], list[dict[str, Any]]]
_log = get_logger(__name__, "ARG-094")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Monitor:
    def __init__(
        self,
        dsn: str,
        store: WormLike | None,
        certificates: Certificates | None,
        evidence_path: Path | None,
        journal_tail: int = 10_000,
        clock: Callable[[], dt.datetime] = _now,
        release: str = "unknown",
    ) -> None:
        self._release = release
        self._dsn = dsn
        self._store = store
        self._certificates = certificates
        self._evidence_path = evidence_path
        self._tail = journal_tail
        self._clock = clock
        self._lock = threading.Lock()
        self._groups: dict[str, list[Observation]] = {}
        self._stalled = -1
        self._ran: dict[str, dt.datetime] = {}

    # ---------- the checks ----------

    def _keep(self, group: str, observations: list[Observation]) -> None:
        with self._lock:
            self._groups[group] = observations
            self._ran[group] = self._clock()

    def _safely(self, group: str, measure: Callable[[], bool]) -> bool:
        try:
            return measure()
        except Exception as exc:  # the gauge says 0; the log says why
            _log.warning("health check failed", extra={"check": group, "error": str(exc)[:200]})
            return False

    def check_journal(self, full: bool = False) -> None:
        scope = "full" if full else "tail"
        ok = self._safely(
            f"journal_{scope}", lambda: journal_ok(self._dsn, None if full else self._tail)
        )
        self._keep(
            f"journal_{scope}",
            [
                Observation(
                    "argos_journal_verify_ok",
                    float(ok),
                    {"scope": scope},
                    help="Whether the chained journal verifies (tail every 5 min, full daily).",
                )
            ],
        )

    def check_security_log(self) -> None:
        ok = self._safely("security_log", lambda: security_log_ok(self._dsn))
        self._keep(
            "security_log",
            [
                Observation(
                    "argos_security_log_verify_ok",
                    float(ok),
                    help="Whether the security log verifies its chain (every 5 min).",
                )
            ],
        )

    def check_worm(self) -> None:
        ok = self._store is not None and worm_canary(self._store, self._clock())
        self._keep(
            "worm",
            [
                Observation(
                    "argos_worm_healthy",
                    float(ok),
                    help="Whether the WORM store kept and gave back the last canary.",
                )
            ],
        )

    def check_domain(self) -> None:
        try:
            observations, stalled = domain_observations(self._dsn)
        except Exception as exc:
            _log.warning("health check failed", extra={"check": "domain", "error": str(exc)[:200]})
            observations, stalled = [], -1
        with self._lock:
            self._stalled = stalled
        self._keep("domain", observations)

    def check_certificates(self) -> None:
        expiring: list[str] | None = None
        if self._certificates is not None:
            try:
                expiring = certificates_expiring(self._certificates(), self._clock())
            except Exception as exc:
                _log.warning(
                    "health check failed", extra={"check": "certificates", "error": str(exc)[:200]}
                )
        value = -1.0 if expiring is None else float(len(expiring))
        self._keep(
            "certificates",
            [
                Observation(
                    "argos_certs_expiring_7d",
                    value,
                    help="Services whose newest certificate expires within 7 days (-1: unknown).",
                )
            ],
        )

    def check_volume(self) -> None:
        ratio = volume_used_ratio(self._evidence_path)
        self._keep(
            "volume",
            []
            if ratio is None
            else [
                Observation(
                    "argos_evidence_volume_used_ratio",
                    round(ratio, 4),
                    help="How full the evidence volume is (0 to 1).",
                )
            ],
        )

    def run_all(self) -> None:
        """Every check once: at start, and in the tests."""
        self.check_journal(full=False)
        self.check_security_log()
        self.check_worm()
        self.check_domain()
        self.check_certificates()
        self.check_volume()

    # ---------- what it gives ----------

    def observations(self) -> list[Observation]:
        with self._lock:
            found = [o for group in self._groups.values() for o in group]
            ran = dict(self._ran)
        found.append(
            Observation(
                "argos_log_records_dropped_total",
                float(loki_dropped()),
                {"service": "argos-health"},
                help="Log lines this process dropped instead of sending them to Loki.",
            )
        )
        found.append(
            Observation(
                "argos_build_info",
                1.0,
                {"version": self._release},
                help="The release the appliance runs.",
            )
        )
        found += [
            Observation(
                "argos_health_check_timestamp_seconds",
                float(at.timestamp()),
                {"check": check},
                help="When each health check last ran.",
            )
            for check, at in sorted(ran.items())
        ]
        return found

    def facts(self) -> dict[str, str]:
        with self._lock:
            stalled = self._stalled
        return as_facts(self.observations(), stalled)

    def publish(self) -> None:
        publish_facts(self._dsn, self.facts(), self._clock())


# ---------- the internal certificates, from the PKI of Vault ----------


def _get(
    url: str, token: str | None, method: str = "GET", context: ssl.SSLContext | None = None
) -> Mapping[str, Any]:
    headers = {"X-Vault-Token": token} if token else {}
    request = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310
        body: Mapping[str, Any] = json.loads(response.read())
        return body


def vault_certificates(pki_url: str, token: Callable[[], str] | None = None) -> Certificates:
    """The certificates the internal CA issued and did not revoke.

    Certificates are public, but Vault asks a token to list them: the AppRole of the service,
    whose policy lists `<pki>/certs` and reads `<pki>/cert/*`, and nothing else of the PKI.
    """

    def fetch() -> list[dict[str, Any]]:
        current = token() if token is not None else None
        listing = _get(f"{pki_url}/certs", current, method="LIST")
        serials = listing.get("data", {}).get("keys", [])
        found: list[dict[str, Any]] = []
        for serial in serials:
            data = _get(f"{pki_url}/cert/{serial}", current).get("data", {})
            if int(data.get("revocation_time") or 0) > 0:
                continue
            certificate = x509.load_pem_x509_certificate(str(data["certificate"]).encode())
            names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if not names:
                continue
            found.append(
                {"common_name": str(names[0].value), "not_after": certificate.not_valid_after_utc}
            )
        return found

    return fetch
