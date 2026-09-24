#!/usr/bin/env bash
# ARG-082 · reseals the data volume after a kernel update, with a window of two seals.
#
#   reseal-after-update.sh prepare   before the reboot into the new kernel (the updater, ARG-086):
#                                    records which TPM slot holds the seal that works today
#   reseal-after-update.sh confirm   after the new kernel booted healthy: seals to the PCRs of
#                                    this boot and only then retires the recorded slot
#
# The old seal is never removed before the new one exists: an update that does not boot as
# expected keeps a volume that opens with the previous kernel (or with the recovery key).
set -euo pipefail

DEV="${ARGOS_DATA_DEVICE:-/dev/disk/by-partlabel/argos-data}"
STATE="${ARGOS_STATE_DIR:-/var/lib/argos}"
PENDING="$STATE/pending-old-tpm-slot"
EXPECTED="$STATE/expected-boot-entry"
PCRS="7+11"

tpm2_slots() {  # the slots of type tpm2, one per line
  systemd-cryptenroll "$DEV" | awk '$2 == "tpm2" { print $1 }'
}

case "${1:-}" in
  prepare)
    mkdir -p "$STATE"
    slots="$(tpm2_slots)"
    if [ -z "$slots" ]; then
      echo "ERROR: the volume has no TPM seal to keep during the update" >&2
      exit 1
    fi
    printf '%s\n' "$slots" > "$PENDING.tmp"
    mv "$PENDING.tmp" "$PENDING"
    logger -t argos-update "old TPM seal recorded before the update: slot(s) $(echo $slots)"
    ;;
  confirm)
    current="$(bootctl status --json=short | sed -n 's/.*"default"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    if [ ! -f "$EXPECTED" ] || [ "$current" != "$(cat "$EXPECTED")" ]; then
      echo "ERROR: this is not the expected boot (${current:-unknown}); the volume is not resealed" >&2
      exit 1
    fi
    systemd-cryptenroll "$DEV" --tpm2-device=auto --tpm2-pcrs="$PCRS"
    if [ -f "$PENDING" ]; then
      while read -r slot; do
        [ -n "$slot" ] && systemd-cryptenroll "$DEV" --wipe-slot="$slot"
      done < "$PENDING"
      rm -f "$PENDING"
    fi
    logger -t argos-update "data volume resealed to PCR ${PCRS} after a healthy boot of ${current}"
    ;;
  *)
    echo "usage: $0 prepare|confirm" >&2
    exit 2
    ;;
esac
