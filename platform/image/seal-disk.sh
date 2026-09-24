#!/usr/bin/env bash
# ARG-082 · seals the LUKS2 data volume to the measured boot (factory enrolment, first boot).
#
# The volume opens only if exactly the expected software booted: PCR 7 (the state of Secure Boot)
# and PCR 11 (the unified kernel image). A removed disk, or another kernel, releases nothing.
#
# The recovery key is for the envelope the client keeps: it is printed on the console of the
# enrolment and never written to a file. Nothing is touched if Secure Boot is off.
#
# ARGOS_DATA_DEVICE overrides the device (tests with stubs); on the appliance it is the partition
# labelled argos-data.
set -euo pipefail

DEV="${ARGOS_DATA_DEVICE:-/dev/disk/by-partlabel/argos-data}"
PCRS="7+11"

echo "[1/4] Secure Boot"
if ! mokutil --sb-state 2>/dev/null | grep -q 'SecureBoot enabled'; then
  echo "ERROR: Secure Boot is not enabled; nothing is sealed" >&2
  exit 1
fi

echo "[2/4] Recovery key, for the envelope of the client"
# Captured in a variable of this process only: printed once, then forgotten.
recovery="$(systemd-cryptenroll --recovery-key "$DEV" | tail -n 1 | tr -d '[:space:]')"
if [ -z "$recovery" ]; then
  echo "ERROR: no recovery key was generated" >&2
  exit 1
fi
printf '\n    RECOVERY KEY (write it down, put it in the envelope, never store it):\n\n    %s\n\n' "$recovery"
unset recovery

echo "[3/4] Sealing to the TPM (PCR ${PCRS})"
# Replaces any previous TPM seal: enrolling again is idempotent.
systemd-cryptenroll "$DEV" --tpm2-device=auto --tpm2-pcrs="$PCRS" --wipe-slot=tpm2

echo "[4/4] crypttab: opened by the TPM at boot, by the recovery key by hand"
line="argos-data $DEV none tpm2-device=auto,timeout=30"
if ! grep -qxF -- "$line" /etc/crypttab 2>/dev/null; then
  grep -v '^argos-data ' /etc/crypttab 2>/dev/null > /etc/crypttab.argos || true
  printf '%s\n' "$line" >> /etc/crypttab.argos
  mv /etc/crypttab.argos /etc/crypttab
  chmod 600 /etc/crypttab
fi
update-initramfs -u
logger -t argos-seal "data volume sealed to PCR ${PCRS}; recovery key handed over on paper"
echo "Sealed. The recovery key was shown once and is not stored anywhere."
