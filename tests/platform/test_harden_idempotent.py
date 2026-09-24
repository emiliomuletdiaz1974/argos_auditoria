"""ARG-081 · `harden.sh` is idempotent and leaves the configuration as expected (F09-14).

It runs twice in an `ubuntu:24.04` container without network and without privileges. The second
run must not change any file under /etc (content, mode or modification time). What needs a real
kernel (loading sysctl, loading the audit rules) or a repository (installing auditd) is skipped
with an explicit SKIP line, never silently: the container is not the appliance.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
IMAGE = REPO / "platform" / "image"
UBUNTU = "ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3"

SCRIPT = r"""
set -eu
snapshot() {
  find /etc -xdev -type f -print0 | sort -z | xargs -0 sha256sum
  find /etc -xdev -printf '%p %m %T@\n' | sort
}
ARGOS_HARDEN_ALLOW_SKIP=1 bash /image/harden.sh > /tmp/first.log 2>&1
snapshot > /tmp/before
ARGOS_HARDEN_ALLOW_SKIP=1 bash /image/harden.sh > /tmp/second.log 2>&1
snapshot > /tmp/after
echo '=== DIFF'; diff /tmp/before /tmp/after || true
echo '=== FIRST'; cat /tmp/first.log
echo '=== SECOND'; cat /tmp/second.log
echo '=== FSTAB'; cat /etc/fstab
echo '=== SYSCTL'; cat /etc/sysctl.d/60-argos-hardening.conf
echo '=== AUDIT'; cat /etc/audit/rules.d/argos.rules
echo '=== SSH'; cat /etc/ssh/sshd_config.d/60-argos.conf
echo '=== MODPROBE'; ls /etc/modprobe.d/
echo '=== LOGINDEFS'; grep -E '^(PASS_MAX_DAYS|PASS_MIN_DAYS|UMASK)' /etc/login.defs
echo '=== STRICT'
set +e
bash /image/harden.sh > /tmp/strict.log 2>&1
echo "exit=$?"
tail -2 /tmp/strict.log
"""


@pytest.fixture(scope="module")
def run() -> dict[str, str]:
    done = subprocess.run(  # noqa: S603 - fixed command against a pinned image
        [  # noqa: S607
            "docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{IMAGE}:/image:ro", UBUNTU, "bash", "-c", SCRIPT,
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=600,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    sections: dict[str, str] = {}
    name = ""
    for line in done.stdout.splitlines():
        if line.startswith("=== "):
            name = line[4:]
            sections[name] = ""
        elif name:
            sections[name] += line + "\n"
    return sections


def test_the_second_run_changes_nothing(run: dict[str, str]) -> None:
    assert run["DIFF"].strip() == "", run["DIFF"]
    assert "changed" not in run["SECOND"], "the second run reports no change"


def test_fstab_gets_each_line_once(run: dict[str, str]) -> None:
    lines = run["FSTAB"].splitlines()
    assert lines.count("tmpfs /dev/shm tmpfs defaults,nodev,nosuid,noexec 0 0") == 1
    assert lines.count("tmpfs /tmp tmpfs defaults,nodev,nosuid,noexec,mode=1777 0 0") == 1


def test_the_configuration_is_the_expected_one(run: dict[str, str]) -> None:
    assert "net.ipv4.ip_forward=1" in run["SYSCTL"], "k3s needs it: documented exception 3.3.1"
    assert "kernel.randomize_va_space=2" in run["SYSCTL"]
    rules = (IMAGE / "audit" / "argos.rules").read_text(encoding="utf-8")
    assert run["AUDIT"] == rules, "the audit rules are the versioned file, as it is"
    assert "PermitRootLogin no" in run["SSH"] and "PasswordAuthentication no" in run["SSH"]
    assert "argos-cramfs.conf" in run["MODPROBE"]
    assert "argos-usb-storage.conf" not in run["MODPROBE"], "the airlock needs removable media"
    assert "PASS_MAX_DAYS\t365" in run["LOGINDEFS"]


def test_what_needs_a_real_kernel_is_skipped_out_loud(run: dict[str, str]) -> None:
    skipped = [line for line in run["FIRST"].splitlines() if line.startswith("SKIP ")]
    assert any("sysctl" in line for line in skipped), run["FIRST"]
    assert any("audit" in line for line in skipped), run["FIRST"]
    assert all(" - " in line for line in skipped), "every skip says why"


def test_without_permission_to_skip_a_missing_piece_is_an_error(run: dict[str, str]) -> None:
    assert "exit=0" not in run["STRICT"], "an image build must not skip in silence"
