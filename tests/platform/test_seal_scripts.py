"""ARG-082 · the scripts that seal the data volume to the TPM, without the hardware (F09-14).

They run in an `ubuntu:24.04` container with `mokutil`, `systemd-cryptenroll`, `bootctl`,
`update-initramfs` and `logger` replaced by stubs that record their calls. What is checked: both
scripts parse; sealing stops before touching anything when Secure Boot is off; the recovery key is
printed and never left in a file; the reseal only runs after the expected boot, and retires the
slot it recorded before the update.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
IMAGE = REPO / "platform" / "image"
UBUNTU = "ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3"
KEY = "fhjk-vnrd-cbtl-hjgv-nkch-rhtf-kclj-dnbt"

STUBS = rf"""
mkdir -p /stubs
cat > /stubs/mokutil <<'EOF'
#!/bin/sh
echo "$SB_STATE"
EOF
cat > /stubs/systemd-cryptenroll <<'EOF'
#!/bin/sh
echo "systemd-cryptenroll $*" >> /tmp/calls
case "$*" in
  *--recovery-key*)
    echo "A secret recovery key has been generated for this volume:"
    echo "    {KEY}" ;;
  *--tpm2-device*|*--wipe-slot*) ;;
  *) printf 'SLOT TYPE\n   0 password\n   1 recovery\n   2 tpm2\n' ;;
esac
EOF
for tool in update-initramfs logger; do
  printf '#!/bin/sh\necho "%s $*" >> /tmp/calls\n' "$tool" > /stubs/$tool
done
cat > /stubs/bootctl <<'EOF'
#!/bin/sh
echo '{{"default":"argos-0.2.0.efi"}}'
EOF
chmod +x /stubs/*
export PATH=/stubs:$PATH ARGOS_DATA_DEVICE=/dev/fake-argos-data
"""


def _in_ubuntu(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed command against a pinned image
        [  # noqa: S607
            "docker", "run", "--rm", "--network", "none", "-v", f"{IMAGE}:/image:ro",
            UBUNTU, "bash", "-c", STUBS + script,
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )  # fmt: skip


@pytest.mark.parametrize("name", ["seal-disk.sh", "reseal-after-update.sh", "harden.sh"])
def test_the_scripts_parse(name: str) -> None:
    done = _in_ubuntu(f"bash -n /image/{name} && echo parsed")
    assert done.returncode == 0 and "parsed" in done.stdout, done.stderr


def test_sealing_stops_when_secure_boot_is_off() -> None:
    done = _in_ubuntu(
        "SB_STATE='SecureBoot disabled' bash /image/seal-disk.sh; echo \"exit=$?\";"
        " test -e /tmp/calls && cat /tmp/calls || echo 'no calls';"
        " test -e /etc/crypttab && echo crypttab || echo 'no crypttab'"
    )
    assert "exit=0" not in done.stdout
    assert "no calls" in done.stdout, "nothing enrolled, nothing wiped"
    assert "no crypttab" in done.stdout
    assert "Secure Boot" in done.stdout + done.stderr


def test_sealing_prints_the_recovery_key_and_leaves_it_nowhere() -> None:
    done = _in_ubuntu(
        "SB_STATE='SecureBoot enabled' bash /image/seal-disk.sh; echo \"exit=$?\";"
        " echo '--- calls'; cat /tmp/calls; echo '--- crypttab'; cat /etc/crypttab;"
        f" echo '--- files with the key'; grep -rlF '{KEY}' /"
        " --exclude-dir=proc --exclude-dir=sys --exclude-dir=stubs --exclude-dir=dev"
        " 2>/dev/null || true; echo '--- end'"
    )
    assert "exit=0" in done.stdout, done.stdout + done.stderr
    assert KEY in done.stdout.split("exit=0")[0], "printed for the envelope"
    files = done.stdout.split("--- files with the key")[1].split("--- end")[0].split()
    assert files == [], f"the recovery key was left in {files}"
    calls = done.stdout.split("--- calls")[1].split("--- crypttab")[0]
    assert "--recovery-key" in calls
    assert "--tpm2-pcrs=7+11" in calls
    crypttab = done.stdout.split("--- crypttab")[1].split("--- files")[0]
    assert "argos-data /dev/fake-argos-data none tpm2-device=auto" in crypttab


def test_the_reseal_refuses_an_unexpected_boot() -> None:
    done = _in_ubuntu(
        "mkdir -p /var/lib/argos && echo argos-0.1.0.efi > /var/lib/argos/expected-boot-entry;"
        ' bash /image/reseal-after-update.sh confirm; echo "exit=$?";'
        " test -e /tmp/calls && grep -c tpm2-device /tmp/calls || echo 'no enrolment'"
    )
    assert "exit=0" not in done.stdout
    assert "no enrolment" in done.stdout


def test_the_reseal_keeps_both_seals_until_the_new_boot_is_confirmed() -> None:
    done = _in_ubuntu(
        "mkdir -p /var/lib/argos && echo argos-0.2.0.efi > /var/lib/argos/expected-boot-entry;"
        " bash /image/reseal-after-update.sh prepare && cat /var/lib/argos/pending-old-tpm-slot;"
        " echo '--- confirm'; bash /image/reseal-after-update.sh confirm; echo \"exit=$?\";"
        " cat /tmp/calls;"
        " test -e /var/lib/argos/pending-old-tpm-slot && echo pending || echo cleared"
    )
    before, after = done.stdout.split("--- confirm")
    assert before.strip().splitlines()[-1] == "2", "the tpm2 slot of the running seal is recorded"
    assert "exit=0" in after, done.stdout + done.stderr
    new_seal = after.index("--tpm2-device=auto --tpm2-pcrs=7+11")
    wipe = after.index("--wipe-slot=2")
    assert new_seal < wipe, "the new seal exists before the old one goes"
    assert "cleared" in after
