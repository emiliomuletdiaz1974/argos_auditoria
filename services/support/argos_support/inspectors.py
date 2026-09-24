"""Read-only inspectors of the orchestrator: Docker Compose in development, Kubernetes on the node.

Every command is a fixed argument list, never a shell line (deviation note ARG-081-090). They only
read: listing, inspecting, logs and events. Deploying is the updater's, through its own port.
"""

import datetime as dt
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from . import ServiceState

TIMEOUT = 60
EVENTS_WINDOW = dt.timedelta(hours=24)
# The life of the containers. Not `exec_*`: every healthcheck is one, and they would bury the rest
# (and the commands they run) under thousands of lines.
LIFECYCLE = ("create", "start", "restart", "die", "kill", "oom", "stop", "destroy", "health_status")


class Runner(Protocol):
    def __call__(self, args: Sequence[str], merge_stderr: bool = False) -> str: ...


def run(args: Sequence[str], merge_stderr: bool = False) -> str:
    """Run a fixed command and return what it wrote; with `merge_stderr`, both streams."""
    done = subprocess.run(  # noqa: S603 - fixed argument lists, no shell
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=TIMEOUT,
    )
    return done.stdout + done.stderr if merge_stderr else done.stdout


def _logs(runner: Runner, args: Sequence[str]) -> str:
    """The logs, or a line that says they are missing: one service never stops the package."""
    try:
        return runner(args, merge_stderr=True)
    except subprocess.CalledProcessError as missing:
        return f"(no logs: the orchestrator answered {missing.returncode})\n"


def _json_lines(text: str) -> list[dict[str, Any]]:
    """`docker compose ps --format json` writes one object per line, or an array (older)."""
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# The development compose also runs the simulated systems of the client. They are not part of the
# appliance (there, they are the client's own systems) and the package never inspects them.
CLIENT_SIMULATORS = ("source-",)


class ComposeInspector:
    def __init__(
        self,
        compose_file: str | Path,
        runner: Runner = run,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        skip: tuple[str, ...] = CLIENT_SIMULATORS,
    ) -> None:
        self._compose = ["docker", "compose", "-f", str(compose_file)]
        self._skip = skip
        self._run = runner
        self._clock = clock
        self._containers: dict[str, dict[str, Any]] = {}

    def _listed(self) -> dict[str, dict[str, Any]]:
        if not self._containers:
            rows = _json_lines(self._run([*self._compose, "ps", "--all", "--format", "json"]))
            self._containers = {
                str(row["Service"]): row
                for row in rows
                if not str(row["Service"]).startswith(self._skip)
            }
        return self._containers

    def services(self) -> list[str]:
        return sorted(self._listed())

    def state(self, service: str) -> ServiceState:
        row = self._listed()[service]
        [detail] = json.loads(self._run(["docker", "inspect", str(row["Name"])]))
        config, status = detail.get("Config") or {}, detail.get("State") or {}
        health = status.get("Health") or {}
        log = health.get("Log") or []
        env = dict(
            item.split("=", 1) if "=" in item else (item, "") for item in config.get("Env") or []
        )
        return ServiceState(
            name=service,
            image=str(config.get("Image") or row.get("Image") or ""),
            health=str(health.get("Status") or status.get("Status") or "unknown"),
            health_output=str(log[-1].get("Output", "")).strip() if log else "",
            env=env,
            mounts=tuple(str(m["Destination"]) for m in detail.get("Mounts") or []),
        )

    def logs(self, service: str, lines: int) -> str:
        args = [*self._compose, "logs", "--no-color", "--no-log-prefix", "--tail", str(lines)]
        return _logs(self._run, [*args, service])

    def events(self) -> list[str]:
        projects = {str(row.get("Project", "")) for row in self._listed().values()} - {""}
        if not projects:
            return []
        now = self._clock()
        args = [
            "docker", "events",
            "--since", str(int((now - EVENTS_WINDOW).timestamp())),
            "--until", str(int(now.timestamp())),
            "--format", "{{json .}}",
        ]  # fmt: skip
        for project in sorted(projects):
            args += ["--filter", f"label=com.docker.compose.project={project}"]
        for kind in LIFECYCLE:
            args += ["--filter", f"event={kind}"]
        lines = []
        for event in _json_lines(self._run(args)):
            attributes = (event.get("Actor") or {}).get("Attributes") or {}
            at = dt.datetime.fromtimestamp(int(event.get("time", 0)), dt.UTC)
            service = attributes.get("com.docker.compose.service", attributes.get("name", "?"))
            action = event.get("Action") or event.get("status") or "?"
            lines.append(f"{at:%Y-%m-%dT%H:%M:%SZ} {service} {action}")
        return lines


class KubernetesInspector:
    def __init__(self, namespace: str, runner: Runner = run) -> None:
        self._namespace = namespace
        self._run = runner
        self._pods: dict[str, dict[str, Any]] = {}

    def _kubectl(self, *args: str) -> list[str]:
        return ["kubectl", "-n", self._namespace, *args]

    def _listed(self) -> dict[str, dict[str, Any]]:
        if not self._pods:
            items = json.loads(self._run(self._kubectl("get", "pods", "-o", "json")))["items"]
            self._pods = {str(item["metadata"]["name"]): item for item in items}
        return self._pods

    def services(self) -> list[str]:
        return sorted(self._listed())

    def state(self, service: str) -> ServiceState:
        pod = self._listed()[service]
        containers = pod.get("spec", {}).get("containers") or []
        conditions = pod.get("status", {}).get("conditions") or []
        ready: dict[str, Any] = next((c for c in conditions if c.get("type") == "Ready"), {})
        # Only literal values reach the scrubber; a reference to a Secret has no value here.
        env = {
            str(e["name"]): str(e.get("value", "")) for c in containers for e in c.get("env") or []
        }
        return ServiceState(
            name=service,
            image=" ".join(str(c.get("image", "")) for c in containers),
            health="healthy" if ready.get("status") == "True" else "unhealthy",
            health_output=str(ready.get("message", "")),
            env=env,
            mounts=tuple(
                str(m["mountPath"]) for c in containers for m in c.get("volumeMounts") or []
            ),
        )

    def logs(self, service: str, lines: int) -> str:
        args = self._kubectl("logs", service, "--all-containers", "--tail", str(lines))
        return _logs(self._run, args)

    def events(self) -> list[str]:
        items = json.loads(self._run(self._kubectl("get", "events", "-o", "json")))["items"]
        return [
            f"{e.get('lastTimestamp') or e.get('eventTime') or '?'} "
            f"{(e.get('involvedObject') or {}).get('name', '?')} {e.get('reason', '?')} "
            f"{e.get('message', '')}".rstrip()
            for e in items
        ]
