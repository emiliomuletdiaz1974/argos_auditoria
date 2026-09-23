"""ARG-084 · the posture, seen from inside every running ARGOS container (P-22).

The compose declares it (`tests/security/test_compose_posture.py`); this checks that it holds once
the containers are up: the process is not root, it has no capability left even in its bounding
set, it cannot gain privileges and its root filesystem is mounted read-only.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "dev" / "compose.yaml")]
SERVICES = (
    "api",
    "webhook-worker",
    "challenge-worker",
    "evidence-worker",
    "evidence-api",
    "verifier",
    "ai-gateway",
    "example",
)
# A process that is not root already has no effective capability and cannot write in `/`: what
# the posture adds is an empty bounding set, no way to gain privileges and a read-only root mount.
PROBE = "\n".join(
    [
        "import os",
        "print('uid', os.getuid())",
        "status = dict(l.split(':', 1) for l in open('/proc/self/status') if ':' in l)",
        "print('capeff', status['CapEff'].strip())",
        "print('capbnd', status['CapBnd'].strip())",
        "print('nonewprivs', status['NoNewPrivs'].strip())",
        "root = [l.split() for l in open('/proc/mounts') if l.split()[1] == '/']",
        "print('root_mount', root[-1][3].split(',')[0])",
    ]
)


@pytest.mark.parametrize("service", SERVICES)
def test_inside_the_container_the_posture_holds(service: str) -> None:
    done = subprocess.run(  # noqa: S603 - fixed command against the development environment
        [*COMPOSE, "exec", "-T", service, "python", "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    seen = dict(line.split(" ", 1) for line in done.stdout.strip().splitlines())
    assert seen["uid"] != "0"
    assert int(seen["capeff"], 16) == 0
    assert int(seen["capbnd"], 16) == 0, "cap_drop: ALL"
    assert seen["nonewprivs"] == "1", "no-new-privileges"
    assert seen["root_mount"] == "ro", "read-only root filesystem"
