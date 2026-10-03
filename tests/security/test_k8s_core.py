"""K-03 · the core of the bench in `argos-core`, validated before it reaches the cluster (DP-22).

Every workload of an ARGOS namespace meets the restricted Pod Security standard that Kubernetes
already enforces there; every image is pinned by digest; whatever keeps data has its volume; and
Vault runs as a server, never in development mode, with no token of any kind in the manifests.
Each component opens its own way in, and only from the namespaces of ARGOS.
"""

from pathlib import Path
from typing import Any

import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
CORE = K8S / "base" / "core"
ARGOS_NAMESPACES = {"argos-core", "argos-services", "argos-ai", "argos-connect"}
WORKLOADS = {"Deployment", "StatefulSet", "Job", "DaemonSet"}


def _documents(folder: Path) -> list[dict[str, Any]]:
    documents = []
    for path in sorted(folder.rglob("*.yaml")):
        documents += [doc for doc in yaml.safe_load_all(path.read_text("utf-8")) if doc]
    return documents


def _workloads() -> list[dict[str, Any]]:
    return [d for d in _documents(K8S / "base") if d.get("kind") in WORKLOADS]


def _pod(workload: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = workload["spec"]["template"]["spec"]
    return spec


def _containers(workload: dict[str, Any]) -> list[dict[str, Any]]:
    pod = _pod(workload)
    return [*pod.get("initContainers", []), *pod["containers"]]


def _named(kind: str, name: str) -> dict[str, Any]:
    [found] = [
        d for d in _documents(CORE) if d.get("kind") == kind and d["metadata"]["name"] == name
    ]
    return found


def test_every_workload_meets_the_restricted_standard() -> None:
    workloads = _workloads()
    assert workloads, "no workload yet"
    for workload in workloads:
        name = workload["metadata"]["name"]
        assert workload["metadata"]["namespace"] in ARGOS_NAMESPACES, name
        pod = _pod(workload)
        assert pod["securityContext"]["runAsNonRoot"] is True, name
        assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        # The token of the service account goes only to the pods that talk to Kubernetes.
        assert pod.get("automountServiceAccountToken") is False or pod.get("serviceAccountName"), (
            name
        )
        for container in _containers(workload):
            context = container["securityContext"]
            assert context["allowPrivilegeEscalation"] is False, (name, container["name"])
            assert context["capabilities"] == {"drop": ["ALL"]}, (name, container["name"])
            assert context["readOnlyRootFilesystem"] is True, (name, container["name"])


def test_every_image_is_pinned_by_digest() -> None:
    for workload in _workloads():
        for container in _containers(workload):
            image = container["image"]
            assert "@sha256:" in image, f"{container['name']}: {image} can move under the tag"


def test_what_keeps_data_keeps_it_in_a_persistent_volume() -> None:
    for workload in _workloads():
        if workload["kind"] == "StatefulSet":
            claims = workload["spec"].get("volumeClaimTemplates", [])
            assert claims, workload["metadata"]["name"]


def test_vault_runs_as_a_server_and_never_in_development_mode() -> None:
    vault = _named("StatefulSet", "vault")
    [container] = _pod(vault)["containers"]
    command = " ".join([*container.get("command", []), *container.get("args", [])])
    assert "server" in command and "-dev" not in command
    names = {e["name"] for e in container.get("env", [])}
    assert not names & {"VAULT_DEV_ROOT_TOKEN_ID", "VAULT_TOKEN", "VAULT_DEV_LISTEN_ADDRESS"}
    config = _named("ConfigMap", "vault-config")["data"]["vault.hcl"]
    assert 'storage "raft"' in config
    assert "disable_mlock = true" in config, "no IPC_LOCK under the restricted standard"
    assert "ui = false" in config


def test_vault_is_ready_even_sealed_so_flux_can_finish_applying() -> None:
    """Sealed or not initialised is the state a person resolves (vault.sh), not a broken pod."""
    [container] = _pod(_named("StatefulSet", "vault"))["containers"]
    path = container["readinessProbe"]["httpGet"]["path"]
    assert "sealedcode=200" in path and "uninitcode=200" in path


def test_only_the_namespaces_of_argos_reach_vault_and_only_on_its_port() -> None:
    policy = _named("NetworkPolicy", "vault")
    assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "vault"}
    [rule] = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8200}]
    [peer] = rule["from"]
    expression = peer["namespaceSelector"]["matchExpressions"][0]
    assert expression == {
        "key": "kubernetes.io/metadata.name",
        "operator": "In",
        "values": sorted(ARGOS_NAMESPACES),
    }


def test_the_base_includes_the_core() -> None:
    kustomization = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "core" in kustomization["resources"]
