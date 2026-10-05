#!/usr/bin/env bash
# K-05 · shows, on this console only, the temporary passwords of the accounts of the bench that the
# Job keycloak-accounts generated. Each one works once: Keycloak asks its owner for a new password
# at the first sign-in (and the people who decide set their TOTP). Run it on the VM:
#
#   bash platform/k8s/bench/accounts.sh
#
# Nothing here writes them anywhere; keep them as you keep the keys of Vault.
set -euo pipefail

sudo k3s kubectl -n argos-core get secret bench-accounts -o json | python3 -c '
import base64, json, sys
data = json.load(sys.stdin).get("data", {})
for name in sorted(data):
    print(f"{name:16} {base64.b64decode(data[name]).decode()}")
'
