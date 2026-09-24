"""ARG-086 · the orchestrators speak in argument lists, never shell lines (F09-10)."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from argos_updater.orchestrator import ComposeOrchestrator, KubernetesOrchestrator


class Recorder:
    def __init__(self, answers: dict[str, str] | None = None, fail: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self._answers = answers or {}
        self._fail = fail

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        joined = " ".join(args)
        if self._fail and self._fail in joined:
            raise subprocess.CalledProcessError(1, list(args))
        for fragment, answer in self._answers.items():
            if fragment in joined:
                return answer
        return ""


def test_kubernetes_sets_the_image_of_the_deployment_and_watches_its_rollout() -> None:
    runner = Recorder({"jsonpath": "registry.argos.local/argos-api@sha256:new"})
    k8s = KubernetesOrchestrator("argos-services", runner)
    k8s.deploy("api", "registry.argos.local/argos-api@sha256:new")
    assert k8s.healthy("api", "registry.argos.local/argos-api@sha256:new", 300)
    assert runner.calls[0] == [
        "kubectl", "set", "image", "deployment/api",
        "api=registry.argos.local/argos-api@sha256:new", "-n", "argos-services",
    ]  # fmt: skip
    assert runner.calls[1] == [
        "kubectl", "rollout", "status", "deployment/api", "-n", "argos-services", "--timeout=300s"
    ]  # fmt: skip


def test_kubernetes_a_rollout_that_does_not_finish_is_not_healthy() -> None:
    runner = Recorder(fail="rollout")
    assert not KubernetesOrchestrator("argos-services", runner).healthy("api", "x", 5)


def test_kubernetes_imports_the_archives_into_containerd() -> None:
    runner = Recorder()
    KubernetesOrchestrator("argos-services", runner).load_images([Path("/b/argos-api.tar")])
    assert runner.calls == [
        ["k3s", "ctr", "-n", "k8s.io", "images", "import", str(Path("/b/argos-api.tar"))]
    ]


def test_compose_tags_the_image_the_compose_runs_and_recreates_only_that_service() -> None:
    config = json.dumps(
        {"name": "argos-dev", "services": {"example": {}, "api": {"image": "argos-api:dev"}}}
    )
    runner = Recorder({"config --format json": config})
    compose = ComposeOrchestrator(Path("compose.yaml"), runner)
    compose.deploy("example", "sha256:new")
    compose.deploy("api", "sha256:new-api")
    tags = [c for c in runner.calls if c[:2] == ["docker", "tag"]]
    assert tags == [
        ["docker", "tag", "sha256:new", "argos-dev-example"],
        ["docker", "tag", "sha256:new-api", "argos-api:dev"],
    ]
    ups = [c for c in runner.calls if "up" in c]
    assert ups[0][-5:] == ["-d", "--no-build", "--no-deps", "--force-recreate", "example"]


def test_no_command_is_a_shell_line() -> None:
    runner = Recorder({"config --format json": json.dumps({"name": "p", "services": {"s": {}}})})
    compose = ComposeOrchestrator(Path("compose.yaml"), runner)
    compose.load_images([Path("a.tar")])
    compose.deploy("s", "sha256:x")
    k8s = KubernetesOrchestrator("ns", runner)
    k8s.deploy("s", "img")
    assert all(isinstance(call, list) and len(call) > 1 for call in runner.calls)
    assert not any(";" in part or "&&" in part for call in runner.calls for part in call)
