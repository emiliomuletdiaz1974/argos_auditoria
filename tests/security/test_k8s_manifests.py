"""ARG-084 · the k3s manifests, validated before there is a cluster to apply them (F09-92).

- Kyverno enforces the restricted posture on every `argos-*` namespace; no policy is left in
  `Audit`, which would only log what it should refuse.
- The seccomp profile of the evidence service denies by default, allows each syscall once and
  none of the ones that open the host (ptrace, mount, kernel modules, bpf…).
- The AppArmor profile of the files connector only reads its mount.
"""

import json
from pathlib import Path
from typing import Any

import yaml

SECURITY = Path(__file__).resolve().parents[2] / "platform" / "k8s" / "security"
NAMESPACES = {"argos-core", "argos-services", "argos-ai", "argos-connect"}
# Syscalls that open the host or the kernel: never in a profile of ARGOS.
FORBIDDEN_SYSCALLS = {
    "ptrace",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "init_module",
    "finit_module",
    "delete_module",
    "kexec_load",
    "kexec_file_load",
    "bpf",
    "perf_event_open",
    "reboot",
    "swapon",
    "swapoff",
    "setns",
    "unshare",
    "open_by_handle_at",
    "process_vm_readv",
    "process_vm_writev",
    "keyctl",
    "add_key",
    "request_key",
    "userfaultfd",
}


def _policies() -> list[dict[str, Any]]:
    documents = yaml.safe_load_all((SECURITY / "pod-baseline.yaml").read_text(encoding="utf-8"))
    return [doc for doc in documents if doc and doc.get("kind") == "ClusterPolicy"]


def _baseline() -> dict[str, Any]:
    [baseline] = [p for p in _policies() if p["metadata"]["name"] == "argos-pod-baseline"]
    return baseline


def test_no_policy_only_audits() -> None:
    policies = _policies()
    assert policies
    for policy in policies:
        action = policy["spec"].get("validationFailureAction")
        assert action == "Enforce", policy["metadata"]["name"]


def test_the_restricted_posture_covers_every_argos_namespace() -> None:
    covered: set[str] = set()
    for rule in _baseline()["spec"]["rules"]:
        for match in rule["match"].get("any", []):
            covered |= set(match["resources"].get("namespaces", []))
    assert covered >= NAMESPACES, sorted(NAMESPACES - covered)
    names = {rule["name"] for rule in _baseline()["spec"]["rules"]}
    assert {"require-restricted-posture", "forbid-host-access"} <= names


def test_the_posture_rule_asks_for_everything_the_compose_asks_for() -> None:
    rules = _baseline()["spec"]["rules"]
    [rule] = [r for r in rules if r["name"] == "require-restricted-posture"]
    container = rule["validate"]["pattern"]["spec"]["containers"][0]["securityContext"]
    assert container["runAsNonRoot"] is True
    assert container["allowPrivilegeEscalation"] is False
    assert container["readOnlyRootFilesystem"] is True
    assert container["capabilities"]["drop"] == ["ALL"]


def test_the_evidence_seccomp_profile_denies_by_default_and_opens_nothing() -> None:
    profile = json.loads((SECURITY / "seccomp" / "evidence.json").read_text(encoding="utf-8"))
    assert profile["defaultAction"] in ("SCMP_ACT_ERRNO", "SCMP_ACT_KILL_PROCESS")
    names = [name for entry in profile["syscalls"] for name in entry["names"]]
    assert len(names) == len(set(names)), "each syscall is allowed once"
    assert not FORBIDDEN_SYSCALLS & set(names), sorted(FORBIDDEN_SYSCALLS & set(names))
    assert all(entry["action"] == "SCMP_ACT_ALLOW" for entry in profile["syscalls"])


def test_the_files_connector_only_reads_its_mount() -> None:
    profile = (SECURITY / "apparmor" / "argos-connector-files").read_text(encoding="utf-8")
    assert "deny /** w," in profile
    assert "/mnt/argos-source/** r," in profile
    assert " w," not in profile.replace("deny /** w,", "")
