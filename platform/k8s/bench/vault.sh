#!/usr/bin/env bash
# K-03 · the person who runs the bench initialises and unseals its Vault. Run it on the VM:
#
#   bash platform/k8s/bench/vault.sh status   # initialised? sealed?
#   bash platform/k8s/bench/vault.sh init     # once: shows 5 unseal keys and the root token
#   bash platform/k8s/bench/vault.sh unseal   # after init and after every restart of the pod
#
# The keys and the root token appear on this console and nowhere else: nothing here writes them to
# a file, a variable of the cluster or a log. Keep them apart from the VM (three of the five
# unseal the vault). Without them the data of Vault cannot be recovered.
set -euo pipefail

KUBECTL=(sudo k3s kubectl -n argos-core)
POD="vault-0"
SHARES=5
THRESHOLD=3

vault_in_pod() {
  "${KUBECTL[@]}" exec -i "$POD" -- vault "$@"
}

initialised() {
  vault_in_pod status -format=json 2>/dev/null | grep -q '"initialized": true'
}

case "${1:-status}" in
  status)
    vault_in_pod status || true
    ;;
  init)
    if initialised; then
      echo "Vault is already initialised: nothing to do. Use 'unseal' if it is sealed." >&2
      exit 1
    fi
    echo "Write down what follows and keep it apart from the VM: it is shown only once."
    "${KUBECTL[@]}" exec -it "$POD" -- vault operator init -key-shares="$SHARES" -key-threshold="$THRESHOLD"
    ;;
  unseal)
    echo "Enter $THRESHOLD of the $SHARES unseal keys, one at a time (they are not shown)."
    for _ in $(seq "$THRESHOLD"); do
      "${KUBECTL[@]}" exec -it "$POD" -- vault operator unseal
    done
    vault_in_pod status || true
    ;;
  *)
    echo "usage: $0 status|init|unseal" >&2
    exit 2
    ;;
esac
