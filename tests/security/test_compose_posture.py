"""ARG-084 · the «admission» of the compose: every ARGOS service declares its restricted posture.

In k3s, Kyverno refuses a pod without the posture (`platform/k8s/security/pod-baseline.yaml`). The
development environment has no admission controller, so this test plays its part: it reads
`deploy/dev/compose.yaml` and fails when a service of ARGOS does not declare, by itself, a user that
is not root, no capabilities, a read-only root filesystem and no privilege escalation. Third-party
images are listed below with the reason each one is left out.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
EVIDENCE_SECCOMP = REPO / "platform" / "k8s" / "security" / "seccomp" / "evidence.json"

# Services that are not ARGOS: databases, platform software and simulated sources of the client.
# Their images decide their own users and write where they were built to write; restricting them
# here would be testing another product. The appliance replaces them (F09-92).
THIRD_PARTY: dict[str, str] = {
    "postgres": "PostgreSQL with AGE and pgvector: the database engine runs as its own user",
    "nats": "NATS server image",
    "temporal-db": "PostgreSQL of Temporal",
    "temporal": "Temporal auto-setup image, development only",
    "keycloak": "Keycloak image",
    "vault": "Vault in development mode",
    "opa": "OPA server image",
    "prometheus": "observability, development only",
    "loki": "observability, development only",
    "grafana": "observability, development only",
    "evidence-store": "VersityGW, the WORM store of development",
    "tsa": "development stand-in of a qualified TSA",
    "edc-mock": "development stand-in of an EDC connector",
    "llm": "llama.cpp server, optional profile",
    "source-postgres": "simulated source of the client",
    "source-mariadb": "simulated source of the client",
    "source-smb": "simulated source of the client",
    "source-s3": "simulated source of the client",
    "source-ldap": "simulated source of the client",
    "source-fhir": "simulated source of the client",
    "source-dicom": "simulated source of the client",
    "source-mssql": "simulated source of the client (heavy profile)",
    "source-oracle": "simulated source of the client (heavy profile)",
}
EVIDENCE = ("evidence-worker", "evidence-api")


def _services() -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return dict(document["services"])


def _argos() -> list[str]:
    return sorted(name for name in _services() if name not in THIRD_PARTY)


def test_every_service_is_either_argos_or_an_explained_exception() -> None:
    services = set(_services())
    assert set(THIRD_PARTY) <= services, sorted(set(THIRD_PARTY) - services)
    assert all(reason.strip() for reason in THIRD_PARTY.values())
    assert {"api", "challenge-worker", "ai-gateway", "evidence-api", "verifier"} <= set(_argos())


@pytest.mark.parametrize("name", _argos())
def test_an_argos_service_declares_the_restricted_posture(name: str) -> None:
    service = _services()[name]
    user = str(service.get("user", ""))
    assert user and user.split(":")[0] not in ("0", "root"), "a user that is not root"
    assert service.get("cap_drop") == ["ALL"], "no capabilities"
    assert service.get("read_only") is True, "read-only root filesystem"
    options = [str(o) for o in service.get("security_opt", [])]
    assert "no-new-privileges:true" in options, "no privilege escalation"
    assert not any("unconfined" in o for o in options), "never without seccomp or AppArmor"
    assert not service.get("privileged"), "never privileged"
    mounts = {str(t).split(":")[0] for t in service.get("tmpfs", [])}
    assert "/tmp" in mounts, "a tmpfs for /tmp"  # noqa: S108 - the path the posture mounts


@pytest.mark.parametrize("name", EVIDENCE)
def test_the_evidence_services_run_under_their_own_seccomp_profile(name: str) -> None:
    options = [str(o) for o in _services()[name].get("security_opt", [])]
    seccomp = [o for o in options if o.startswith(("seccomp=", "seccomp:"))]
    assert seccomp, "the evidence service declares its own seccomp profile"
    assert Path(seccomp[0][len("seccomp=") :]).name == EVIDENCE_SECCOMP.name
