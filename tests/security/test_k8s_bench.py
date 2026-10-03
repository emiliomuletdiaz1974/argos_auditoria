"""K-01 · the k3s manifests of the bench: namespaces, a network denied by default, and no secrets.

The bench is a Google Cloud VM with synthetic data only (DP-20, desviación ARG-002-003). Its
manifests are validated here before there is a cluster: every namespace of ARGOS denies all
traffic in and out unless a later policy opens it, and the restricted Pod Security standard is
enforced by Kubernetes itself, under the Kyverno policy of ADR-0014. Nothing secret is versioned.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
BASE = K8S / "base"
OVERLAY = K8S / "overlays" / "bench-gcp"
ARGOS_NAMESPACES = {"argos-core", "argos-services", "argos-ai", "argos-connect"}
BENCH_NAMESPACES = {"bench-sources"}
# A key named password or token (not `automountServiceAccountToken`), or a private key.
SECRET_LIKE = re.compile(
    r"dev-only-|(?<![a-z])password\s*:|(?<![a-z])token\s*:|BEGIN [A-Z ]*PRIVATE KEY", re.I
)


def _documents(folder: Path) -> list[dict[str, Any]]:
    documents = []
    for path in sorted(folder.rglob("*.yaml")):
        # Only objects of Kubernetes: the seeder keeps its list of secrets as plain YAML.
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _kind(folder: Path, kind: str) -> list[dict[str, Any]]:
    return [doc for doc in _documents(folder) if doc.get("kind") == kind]


def test_every_namespace_of_the_bench_is_declared() -> None:
    names = {doc["metadata"]["name"] for doc in _kind(BASE, "Namespace")}
    assert names == ARGOS_NAMESPACES | BENCH_NAMESPACES


def test_kubernetes_enforces_the_restricted_standard_on_argos() -> None:
    for namespace in _kind(BASE, "Namespace"):
        labels = namespace["metadata"].get("labels", {})
        if namespace["metadata"]["name"] in ARGOS_NAMESPACES:
            assert labels.get("pod-security.kubernetes.io/enforce") == "restricted", namespace
        else:
            # The simulated sources are third-party images with root and writable roots.
            assert labels.get("pod-security.kubernetes.io/enforce") == "baseline", namespace


def test_every_namespace_denies_all_traffic_by_default() -> None:
    denied = {}
    for policy in _kind(BASE, "NetworkPolicy"):
        spec = policy["spec"]
        if spec.get("podSelector") == {} and set(spec.get("policyTypes", [])) == {
            "Ingress",
            "Egress",
        }:
            denied[policy["metadata"]["namespace"]] = spec
    assert set(denied) == ARGOS_NAMESPACES | BENCH_NAMESPACES
    for namespace, spec in denied.items():
        assert not spec.get("ingress"), f"{namespace}: the default lets something in"
        # The only way out a pod has by default is the cluster DNS.
        for rule in spec.get("egress", []):
            ports = {(p.get("protocol", "TCP"), p["port"]) for p in rule.get("ports", [])}
            assert ports == {("UDP", 53), ("TCP", 53)}, f"{namespace}: {rule}"
            [peer] = rule["to"]
            assert peer["namespaceSelector"]["matchLabels"] == {
                "kubernetes.io/metadata.name": "kube-system"
            }
            assert peer["podSelector"]["matchLabels"] == {"k8s-app": "kube-dns"}


def test_the_overlay_builds_only_from_files_that_exist() -> None:
    def resources(folder: Path) -> list[Path]:
        kustomization = yaml.safe_load((folder / "kustomization.yaml").read_text("utf-8"))
        found = []
        for entry in kustomization.get("resources", []):
            target = (folder / entry).resolve()
            assert target.exists(), f"{folder.name}: {entry} does not exist"
            found += resources(target) if target.is_dir() else [target]
        return found

    built = resources(OVERLAY)
    assert {path.name for path in built} >= {"namespaces.yaml", "default-deny.yaml"}


def test_nothing_secret_is_versioned_with_the_manifests() -> None:
    assert not _kind(K8S, "Secret"), "secrets are generated in the cluster, never versioned"
    for path in sorted(K8S.rglob("*.yaml")):
        assert not SECRET_LIKE.search(path.read_text("utf-8")), path.relative_to(K8S)


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is not installed here")
def test_kustomize_builds_the_overlay() -> None:
    built = subprocess.run(  # noqa: S603 - fixed command
        ["kubectl", "kustomize", str(OVERLAY)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    documents = [doc for doc in yaml.safe_load_all(built) if doc]
    assert [d["kind"] for d in documents].count("Namespace") == 5
    denials = [d for d in documents if d["metadata"]["name"] == "default-deny"]
    assert len(denials) == 5
