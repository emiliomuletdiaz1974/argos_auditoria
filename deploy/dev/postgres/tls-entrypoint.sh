#!/bin/sh
# ARG-083 · PostgreSQL of the development environment speaks TLS 1.3 only (F09-06).
#
# cert-issuer leaves the certificate of `postgres` in /run/tls, owned by its own user. PostgreSQL
# only accepts a private key owned by itself with mode 0600, so this copies the three files into
# its own folder first, and copies them again and reloads the server whenever cert-issuer renews
# them (every 20 days): the connections already open are not cut.
set -eu

SOURCE=/run/tls
TARGET=/var/lib/postgresql/tls

install_certificates() {
  mkdir -p "$TARGET"
  cp "$SOURCE/tls.crt" "$TARGET/server.crt"
  cp "$SOURCE/tls.key" "$TARGET/server.key"
  cp "$SOURCE/ca.crt" "$TARGET/ca.crt"
  chown -R postgres:postgres "$TARGET"
  chmod 600 "$TARGET/server.key"
}

install_certificates
(
  last=$(md5sum < "$SOURCE/tls.crt")
  while sleep 60; do
    now=$(md5sum < "$SOURCE/tls.crt")
    if [ "$now" != "$last" ] && install_certificates \
        && gosu postgres pg_ctl reload -D "$PGDATA" >/dev/null; then
      last=$now
    fi
  done
) &

exec docker-entrypoint.sh "$@"
