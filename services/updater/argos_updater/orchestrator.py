"""ARG-086 · where the updater changes the system: Docker Compose now, Kubernetes on the appliance.

Both speak through a runner that takes a list of arguments, never a shell line (the version and the
image come from a signed manifest, but they are still never interpolated into a command).
"""

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

Runner = Callable[[Sequence[str]], str]


def run(args: Sequence[str]) -> str:
    done = subprocess.run(  # noqa: S603 - a list of arguments, never a shell
        list(args), check=True, capture_output=True, text=True
    )
    return done.stdout


class ComposeOrchestrator:
    """The development environment: `docker load`, a new tag and `docker compose up` per service."""

    def __init__(self, compose_file: Path, runner: Runner = run, poll: float = 2.0) -> None:
        self._file = compose_file
        self._run = runner
        self._poll = poll

    def _compose(self, *args: str) -> str:
        return self._run(["docker", "compose", "-f", str(self._file), *args])

    def _image_name(self, service: str) -> str:
        """The image the compose runs for a service: its `image:`, or the one compose names."""
        config = json.loads(self._compose("config", "--format", "json"))
        declared = config["services"][service].get("image")
        return str(declared) if declared else f"{config['name']}-{service}"

    def _container(self, service: str) -> str:
        return self._compose("ps", "-q", service).strip()

    def load_images(self, archives: list[Path]) -> None:
        for archive in archives:
            self._run(["docker", "load", "-i", str(archive)])

    def current_image(self, service: str) -> str:
        container = self._container(service)
        return self._run(["docker", "inspect", "-f", "{{.Image}}", container]).strip()

    def deploy(self, service: str, image: str) -> None:
        self._run(["docker", "tag", image, self._image_name(service)])
        self._compose("up", "-d", "--no-build", "--no-deps", "--force-recreate", service)

    def healthy(self, service: str, image: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            container = self._container(service)
            if container:
                state = json.loads(self._run(["docker", "inspect", "-f", "{{json .}}", container]))
                health = (state["State"].get("Health") or {}).get("Status")
                running_ok = health == "healthy" if health else state["State"]["Running"]
                if state["Image"] == image and running_ok:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self._poll)


class KubernetesOrchestrator:
    """The appliance (k3s): images imported into containerd, a deployment per service.

    Written and tested with a double until there is a cluster (F09-92, deviation note ARG-081-090).
    """

    def __init__(self, namespace: str, runner: Runner = run) -> None:
        self._namespace = namespace
        self._run = runner

    def load_images(self, archives: list[Path]) -> None:
        for archive in archives:
            self._run(["k3s", "ctr", "-n", "k8s.io", "images", "import", str(archive)])

    def current_image(self, service: str) -> str:
        return self._run(
            [
                "kubectl", "get", "deployment", service, "-n", self._namespace,
                "-o", "jsonpath={.spec.template.spec.containers[0].image}",
            ]
        ).strip()  # fmt: skip

    def deploy(self, service: str, image: str) -> None:
        self._run(
            [
                "kubectl", "set", "image", f"deployment/{service}", f"{service}={image}",
                "-n", self._namespace,
            ]
        )  # fmt: skip

    def healthy(self, service: str, image: str, timeout: float) -> bool:
        try:
            self._run(
                [
                    "kubectl", "rollout", "status", f"deployment/{service}",
                    "-n", self._namespace, f"--timeout={int(timeout)}s",
                ]
            )  # fmt: skip
        except subprocess.CalledProcessError:
            return False
        return self.current_image(service) == image
