#!/bin/sh
# ARG-083 · NATS of the development environment, reloading its certificate when cert-issuer
# renews it (F09-06). `--signal reload` makes the server read its configuration and certificate
# again without dropping the clients.
set -eu

nats-server -c /etc/nats/nats.conf &
pid=$!
trap 'kill -TERM "$pid" 2>/dev/null' TERM INT

last=$(md5sum < /run/tls/tls.crt)
while kill -0 "$pid" 2>/dev/null; do
  sleep 60 &
  wait $! || true
  now=$(md5sum < /run/tls/tls.crt)
  if [ "$now" != "$last" ] && nats-server --signal reload="$pid"; then
    last=$now
  fi
done
wait "$pid"
