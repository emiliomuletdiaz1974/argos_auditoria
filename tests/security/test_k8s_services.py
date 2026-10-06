"""K-06 · the seven services of ARGOS in `argos-services`, validated before they reach the cluster.

Each service signs in to Vault with its own service account and gets there its database credential
(nobody hands it a token, ADR-0014 point 3); each one has its own certificate from cert-manager for
the mutual TLS of ARGOS and to check PostgreSQL; each one reaches only what it uses. No assistant:
without a GPU there is no model and the API answers 503 (F06-01 arrives with it). The restricted
standard and the digests are checked for every workload by test_k8s_core.
"""

from pathlib import Path
from typing import Any

import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
SERVICES_DIR = K8S / "base" / "services"
NAMESPACE = "argos-services"

# deployment: (service account, image, module, database role, NATS user)
SERVICES = {
    "api": ("api", "argos-api", "argos_api.main", "svc-api", None),
    "webhook-worker": (
        "webhook",
        "argos-api",
        "argos_api.webhooks.worker",
        "svc-webhook",
        "webhook",
    ),
    "challenge-worker": (
        "challenge",
        "argos-challenge-engine",
        "argos_challenges.worker",
        "svc-challenge",
        "challenge",
    ),
    "evidence-worker": (
        "evidence",
        "argos-evidence",
        "argos_evidence.worker",
        "svc-evidence",
        "evidence",
    ),
    "evidence-api": ("evidence", "argos-evidence", "argos_evidence.api", "svc-evidence", None),
    "health": ("health", "argos-health", "argos_health.app", "svc-health", None),
    "verifier": ("verifier", "argos-verifier", "argos_verifier.main", None, None),
    # K-07: the inventory, which reads the simulated sources and fills the graph.
    "inventory-scheduler": (
        "inventory",
        "argos-api",
        "argos_inventory.scheduler.worker",
        "svc-inventory",
        "inventory",
    ),
    "inventory-ingest": (
        "inventory",
        "argos-api",
        "argos_inventory.ingest.main",
        "svc-inventory",
        "inventory",
    ),
}
# K-07: who reads the simulated sources (bench-sources), and on which ports.
SOURCE_PORTS = [5432, 3306, 445, 7070, 636, 8080, 4242]
READ_SOURCES = {"inventory-scheduler", "challenge-worker"}
CORE = {
    "postgres": 5432,
    "vault": 8200,
    "temporal": 7233,
    "nats": 4222,
    "opa": 8181,
    "keycloak": 8080,
    "evidence-store": 7070,
    "tsa": 3180,
    "loki": 3100,  # K-10: every service pushes its own logs
    "prometheus": 9090,  # K-10: the operation screen of the API
}
REACHES = {
    "api": {
        "postgres",
        "vault",
        "temporal",
        "keycloak",
        "evidence-store",
        "tsa",
        "loki",
        "prometheus",
    },
    "webhook-worker": {"postgres", "vault", "temporal", "nats", "loki"},
    "challenge-worker": {"postgres", "vault", "temporal", "nats", "opa", "loki"},
    "evidence-worker": {"postgres", "vault", "temporal", "nats", "evidence-store", "tsa", "loki"},
    "evidence-api": {"postgres", "vault", "evidence-store", "tsa", "loki"},
    "health": {"postgres", "vault", "evidence-store", "loki"},
    "verifier": set(),
    "inventory-scheduler": {"postgres", "vault", "temporal", "nats", "loki"},
    "inventory-ingest": {"postgres", "vault", "nats", "loki"},
}


def _documents() -> list[dict[str, Any]]:
    documents = []
    for path in sorted(SERVICES_DIR.rglob("*.yaml")):
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _named(kind: str, name: str) -> dict[str, Any]:
    [found] = [d for d in _documents() if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found


def _pod(name: str) -> dict[str, Any]:
    pod: dict[str, Any] = _named("Deployment", name)["spec"]["template"]["spec"]
    return pod


def _env(name: str) -> dict[str, Any]:
    [container] = _pod(name)["containers"]
    return {e["name"]: e.get("value", e.get("valueFrom")) for e in container.get("env", [])}


def test_the_base_includes_the_services() -> None:
    base = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "services" in base["resources"]


def test_each_service_runs_its_image_and_module_in_argos_services() -> None:
    for name, (account, image, module, _, _) in SERVICES.items():
        deployment = _named("Deployment", name)
        assert deployment["metadata"]["namespace"] == NAMESPACE
        [container] = _pod(name)["containers"]
        assert container["image"] == image, name
        assert container["command"] == ["/app/.venv/bin/python", "-m", module], name
        assert _pod(name)["serviceAccountName"] == account, name


def test_no_service_carries_a_vault_token_or_a_development_value() -> None:
    text = "\n".join(p.read_text("utf-8") for p in sorted(SERVICES_DIR.rglob("*.yaml")))
    assert "VAULT_TOKEN" not in text
    assert "dev-only" not in text and "value: root" not in text


def test_each_service_signs_in_to_vault_with_its_own_account() -> None:
    for name, (account, _, _, role, _) in SERVICES.items():
        env, pod = _env(name), _pod(name)
        if role is None:
            assert pod["automountServiceAccountToken"] is False, f"{name} does not reach Vault"
            assert "ARGOS_VAULT_KUBERNETES_ROLE" not in env
            continue
        assert pod["automountServiceAccountToken"] is True, name
        assert env["ARGOS_VAULT_KUBERNETES_ROLE"] == account, name
        assert env["ARGOS_DATABASE_VAULT_ROLE"] == role, name
        assert env["ARGOS_VAULT_ADDR"] == "http://vault.argos-core.svc:8200"
        assert env["ARGOS_DATABASE_URL"] == (
            "postgresql://postgres.argos-core.svc:5432/argos?service=argos"
            "&sslmode=verify-full&sslrootcert=/run/tls/ca.crt"
        ), name
        assert env["ARGOS_ENVIRONMENT"] == "staging", name


def test_each_service_account_exists_and_only_its_own_pods_mount_its_token() -> None:
    for account in {a for a, *_ in SERVICES.values()}:
        sa = _named("ServiceAccount", account)
        assert sa["metadata"]["namespace"] == NAMESPACE
        assert sa["automountServiceAccountToken"] is False, "only the pod that needs it mounts it"


def test_each_service_with_a_database_has_its_own_certificate() -> None:
    for name, (account, _, _, role, _) in SERVICES.items():
        if role is None:
            continue
        certificate = _named("Certificate", account)
        spec = certificate["spec"]
        assert spec["secretName"] == f"{account}-tls"
        assert set(spec["dnsNames"]) == {
            f"{account}.{NAMESPACE}.svc",
            f"{account}.{NAMESPACE}.svc.cluster.local",
        }
        assert spec["issuerRef"] == {"name": "vault-bench", "kind": "ClusterIssuer"}
        assert spec["privateKey"] == {"algorithm": "ECDSA", "size": 256, "rotationPolicy": "Always"}
        assert "client auth" in spec["usages"] and "server auth" in spec["usages"]
        volumes = {v["name"]: v for v in _pod(name)["volumes"]}
        assert volumes["tls"]["secret"]["secretName"] == f"{account}-tls", name
        assert _env(name)["ARGOS_TLS_DIR"] == "/run/tls"


def test_the_nats_password_of_each_worker_is_its_own() -> None:
    for name, (_, _, _, _, user) in SERVICES.items():
        env = _env(name)
        if user is None:
            assert "ARGOS_NATS_PASSWORD" not in env, name
            continue
        assert env["ARGOS_NATS_USER"] == user
        assert env["ARGOS_NATS_PASSWORD"] == {"secretKeyRef": {"name": "nats-users", "key": user}}
        assert env["ARGOS_NATS_URL"] == "tls://nats.argos-core.svc:4222"


def test_each_service_reaches_only_what_it_uses() -> None:
    for name, wanted in REACHES.items():
        policy = _named("NetworkPolicy", name)
        assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": name}
        reached = set()
        reads_sources = False
        for rule in policy["spec"].get("egress", []):
            [target] = rule["to"]
            if target["namespaceSelector"]["matchLabels"] == {
                "kubernetes.io/metadata.name": "bench-sources"
            }:
                assert "podSelector" not in target
                assert sorted(p["port"] for p in rule["ports"]) == sorted(SOURCE_PORTS), name
                reads_sources = True
                continue
            assert target["namespaceSelector"]["matchLabels"] == {
                "kubernetes.io/metadata.name": "argos-core"
            }
            component = target["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
            [port] = rule["ports"]
            assert port["port"] == CORE[component], (name, component)
            reached.add(component)
        assert reached == wanted, name
        assert reads_sources == (name in READ_SOURCES), name


def test_the_assistant_is_off_without_a_gpu() -> None:
    assert "ARGOS_AI_GATEWAY_URL" not in _env("api")


def test_the_verifier_believes_only_its_trust_file_and_reaches_nothing() -> None:
    env = _env("verifier")
    assert env["ARGOS_VERIFIER_TRUST_FILE"] == "/etc/argos-verifier/trust.json"
    volumes = {v["name"]: v for v in _pod("verifier")["volumes"]}
    assert volumes["trust"]["configMap"]["name"] == "verifier-trust"
    assert "egress" not in _named("NetworkPolicy", "verifier")["spec"]


def test_the_trust_of_the_verifier_is_written_by_a_job_that_touches_only_that() -> None:
    role = _named("Role", "verifier-trust")
    rules = {(tuple(r["resources"]), tuple(sorted(r["verbs"]))) for r in role["rules"]}
    assert rules == {(("configmaps",), ("create",)), (("configmaps",), ("get", "update"))}
    [named] = [r for r in role["rules"] if "resourceNames" in r]
    assert named["resourceNames"] == ["verifier-trust"]
    job = _named("Job", "verifier-trust")
    pod = job["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "verifier-trust"
    [container] = pod["containers"]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["ARGOS_VAULT_KUBERNETES_ROLE"] == "verifier-trust"
    policy = _named("NetworkPolicy", "verifier-trust")
    reached = {
        rule["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
        for rule in policy["spec"]["egress"]
        if "to" in rule
    }
    assert reached == {"vault", "tsa"}


def test_the_evidence_runs_under_its_own_seccomp_profile() -> None:
    """K-09: the profile of ARG-084, loaded on the node by install.sh (argos/evidence.json)."""
    for name in ("evidence-worker", "evidence-api"):
        assert _pod(name)["securityContext"]["seccompProfile"] == {
            "type": "Localhost",
            "localhostProfile": "argos/evidence.json",
        }, name


def test_the_cluster_applies_the_posture_of_argos() -> None:
    """K-09 (ADR-0014): argos-pod-baseline, the same file the appliance will apply."""
    base = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "../security" in base["resources"]
    security = yaml.safe_load((K8S / "security" / "kustomization.yaml").read_text("utf-8"))
    # The issuer and the image verification of the appliance are not the bench's (deviation note).
    assert security["resources"] == ["pod-baseline.yaml"]
