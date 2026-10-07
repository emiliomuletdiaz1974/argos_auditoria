#!/usr/bin/env bash
# K-05 · shows, on this console only, the temporary passwords of the accounts of the bench that the
# Job keycloak-accounts generated. Each one works once: Keycloak asks its owner for a new password
# at the first sign-in (and the people who decide set their TOTP). Run it on the VM:
#
#   bash platform/k8s/bench/accounts.sh                 show the passwords that are kept
#   bash platform/k8s/bench/accounts.sh reset dpo.test  another temporary password for an account
#                                                       and its second factor to be set up again
#
# K-11: the reset runs the same Job once, in a copy of its own (keycloak-accounts-reset) that names
# the accounts; the Job Flux manages is never touched. Nothing here writes a password anywhere but
# the secret of the cluster; keep them as you keep the keys of Vault.
set -euo pipefail

show() {
  sudo k3s kubectl -n argos-core get secret bench-accounts -o json | python3 -c '
import base64, json, sys
data = json.load(sys.stdin).get("data", {})
for name in sorted(data):
    print(f"{name:16} {base64.b64decode(data[name]).decode()}")
'
}

reset() {
  [ "$#" -ge 1 ] || { echo "usage: $0 reset <account> [<account>...]" >&2; exit 2; }
  local users
  users=$(IFS=,; echo "$*")
  sudo k3s kubectl -n argos-core delete job keycloak-accounts-reset --ignore-not-found
  sudo k3s kubectl -n argos-core get job keycloak-accounts -o json | RESET_USERS="$users" python3 -c '
import json, os, sys
job = json.load(sys.stdin)
job["metadata"] = {"name": "keycloak-accounts-reset", "namespace": "argos-core"}
job.pop("status", None)
template = job["spec"]["template"]
template["metadata"].pop("labels", None)
template["metadata"]["labels"] = {"app.kubernetes.io/name": "keycloak-accounts"}
job["spec"].pop("selector", None)
env = template["spec"]["containers"][0]["env"]
env.append({"name": "RESET_USERS", "value": os.environ["RESET_USERS"]})
json.dump(job, sys.stdout)
' | sudo k3s kubectl apply -f -
  sudo k3s kubectl -n argos-core wait --for=condition=complete job/keycloak-accounts-reset --timeout=120s
  show
}

case "${1:-show}" in
  show) show ;;
  reset) shift; reset "$@" ;;
  *) echo "usage: $0 [show | reset <account>...]" >&2; exit 2 ;;
esac
