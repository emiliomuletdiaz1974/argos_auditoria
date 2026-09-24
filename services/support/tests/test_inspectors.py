"""ARG-088 · the inspectors read the orchestrator, with fixed argument lists (F09-11)."""

import datetime as dt
import json
import subprocess
from collections.abc import Sequence

from argos_support.inspectors import ComposeInspector, KubernetesInspector

NOW = dt.datetime(2026, 9, 24, 10, 0, tzinfo=dt.UTC)


class Runner:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str], merge_stderr: bool = False) -> str:
        self.calls.append(list(args))
        for key, answer in self.answers.items():
            if key in " ".join(args):
                return answer
        return ""


def test_compose_reads_services_state_logs_and_events() -> None:
    ps = "\n".join(
        json.dumps(line)
        for line in (
            {"Service": "api", "Name": "dev-api-1", "Project": "dev", "Image": "argos-api:dev"},
            {"Service": "nats", "Name": "dev-nats-1", "Project": "dev", "Image": "nats:2"},
            {"Service": "source-smb", "Name": "dev-source-smb-1", "Project": "dev", "Image": "x"},
        )
    )
    inspect = json.dumps(
        [
            {
                "Config": {
                    "Image": "argos-api:dev",
                    "Env": ["ARGOS_VAULT_TOKEN=root", "PATH=/bin"],
                },
                "Mounts": [{"Destination": "/run/tls"}],
                "State": {
                    "Status": "running",
                    "Health": {"Status": "healthy", "Log": [{"Output": '{"status":"ok"}'}]},
                },
            }
        ]
    )
    event = json.dumps(
        {"Action": "restart", "time": 1790244000,
         "Actor": {"Attributes": {"com.docker.compose.service": "api"}}}
    )  # fmt: skip
    runner = Runner({" ps ": ps, "inspect dev-api-1": inspect, " logs ": "line\n", "events": event})
    inspector = ComposeInspector("deploy/dev/compose.yaml", runner=runner, clock=lambda: NOW)

    assert inspector.services() == ["api", "nats"], (
        "the simulated sources of the client are not ARGOS"
    )
    state = inspector.state("api")
    assert state.image == "argos-api:dev"
    assert state.health == "healthy"
    assert state.health_output == '{"status":"ok"}'
    assert state.env == {"ARGOS_VAULT_TOKEN": "root", "PATH": "/bin"}
    assert state.mounts == ("/run/tls",)
    assert inspector.logs("api", 500) == "line\n"
    [line] = inspector.events()
    assert line.endswith("api restart")

    for call in runner.calls:
        assert call[0] == "docker" and all(isinstance(arg, str) for arg in call)
    logs = next(c for c in runner.calls if "logs" in c)
    assert logs[-3:] == ["--tail", "500", "api"]
    events = next(c for c in runner.calls if "events" in c)
    assert "label=com.docker.compose.project=dev" in events
    assert "--until" in events, "a bounded window: the command ends"
    assert "event=die" in events and "event=exec_start" not in events, "not the healthchecks"


def test_kubernetes_reads_pods_logs_and_events() -> None:
    pods = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "api-7c9f"},
                    "spec": {
                        "containers": [
                            {
                                "image": "registry.local/argos-api:0.1.0",
                                "env": [{"name": "ARGOS_LOG_LEVEL", "value": "INFO"},
                                        {"name": "ARGOS_TOKEN", "valueFrom": {"secretKeyRef": {}}}],
                                "volumeMounts": [{"mountPath": "/run/tls"}],
                            }
                        ]
                    },
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                }
            ]
        }
    )  # fmt: skip
    events = json.dumps(
        {"items": [{"lastTimestamp": "2026-09-24T09:00:00Z", "reason": "BackOff",
                    "involvedObject": {"name": "api-7c9f"}, "message": "restarting"}]}
    )  # fmt: skip
    runner = Runner({"get pods": pods, "get events": events, "logs": "l\n"})
    inspector = KubernetesInspector("argos-services", runner=runner)

    assert inspector.services() == ["api-7c9f"]
    state = inspector.state("api-7c9f")
    assert state.health == "healthy"
    assert state.env == {"ARGOS_LOG_LEVEL": "INFO", "ARGOS_TOKEN": ""}
    assert state.mounts == ("/run/tls",)
    assert inspector.logs("api-7c9f", 500) == "l\n"
    assert inspector.events() == ["2026-09-24T09:00:00Z api-7c9f BackOff restarting"]
    for call in runner.calls:
        assert call[0] == "kubectl" and "-n" in call


def test_a_service_without_logs_says_so_and_does_not_stop_the_package() -> None:
    def runner(args: Sequence[str], merge_stderr: bool = False) -> str:
        raise subprocess.CalledProcessError(1, list(args))

    compose = ComposeInspector("deploy/dev/compose.yaml", runner=runner)
    assert compose.logs("challenge-api", 500) == "(no logs: the orchestrator answered 1)\n"
    kubernetes = KubernetesInspector("argos-services", runner=runner)
    assert kubernetes.logs("api-7c9f", 500) == "(no logs: the orchestrator answered 1)\n"
