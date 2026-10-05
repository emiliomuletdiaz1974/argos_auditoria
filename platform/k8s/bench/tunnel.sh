#!/usr/bin/env bash
# K-08 · the public entry of the bench through SSH, while the firewall of the VM keeps 80 and 443
# closed. Run it on the computer of whoever tests (Git Bash or any shell with ssh), not on the VM:
#
#   bash platform/k8s/bench/tunnel.sh geographoss2000@34.134.21.66
#
# It takes port 443 of this computer to the Traefik of the VM, so the API and the sign-in answer on
# their final names. Point those names here first, with these two lines in the hosts file
# (C:\Windows\System32\drivers\etc\hosts on Windows, /etc/hosts elsewhere), and take them out the
# day the firewall opens:
#
#   127.0.0.1 api.34-134-21-66.sslip.io
#   127.0.0.1 id.34-134-21-66.sslip.io
#
# Until Let's Encrypt can reach port 80, Traefik answers with its own certificate: the browser and
# Postman warn once, and the warning goes away with the real certificate. Ctrl+C closes the tunnel.
set -euo pipefail

target="${1:?usage: $0 user@host}"
echo "tunnel open: https://api.34-134-21-66.sslip.io and https://id.34-134-21-66.sslip.io (Ctrl+C to close)"
exec ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:443:127.0.0.1:443 "$target"
