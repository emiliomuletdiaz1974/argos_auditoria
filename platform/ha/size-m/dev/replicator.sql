-- ARG-095 · the role that streams the WAL to the standby of the size M pair (development only).
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'dev-only-ha-replication';
