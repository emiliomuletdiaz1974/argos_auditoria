#!/bin/sh
# ARG-095 · a node of the size M pair of the development environment (profile `ha`, F10-09).
#
# With PRIMARY_HOST empty the node starts as a primary (the image initialises it). With
# PRIMARY_HOST set and an empty data folder it clones the primary with pg_basebackup, creates its
# replication slot there and starts as a physical standby (-R writes standby.signal and the
# connection). A node that already has data starts as whatever its data says: rejoin.py empties it
# first when an old primary must come back as a replica.
set -eu

if [ -n "${PRIMARY_HOST:-}" ] && [ ! -s "$PGDATA/PG_VERSION" ]; then
  until pg_isready -q -h "$PRIMARY_HOST" -U replicator; do sleep 1; done
  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"
  gosu postgres env PGPASSWORD="$REPLICATION_PASSWORD" pg_basebackup \
    -h "$PRIMARY_HOST" -U replicator -D "$PGDATA" -R -X stream -C -S "slot_${NODE_NAME}"
fi

exec docker-entrypoint.sh postgres \
  -c shared_preload_libraries=age \
  -c hba_file=/etc/postgresql/pg_hba.conf \
  -c wal_level=replica -c max_wal_senders=5 -c max_replication_slots=5 -c hot_standby=on
