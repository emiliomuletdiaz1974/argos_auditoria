-- ARG-023 · Inventory deltas between scan runs and immutable snapshots of the graph
-- (deviation note ARG-021-023). Nothing here is ever updated in place: deltas are recorded once
-- per (run, kind, node) and snapshots are frozen by trigger.
CREATE TABLE argos.inventory_deltas (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      uuid NOT NULL REFERENCES argos.scan_runs(id),
  kind        text NOT NULL CHECK (kind IN ('appeared', 'disappeared', 'anomalous_growth')),
  node_label  text NOT NULL,
  node_key    text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, kind, node_key)
);

CREATE TABLE argos.inventory_snapshots (
  id            uuid PRIMARY KEY,
  label         text NOT NULL,
  taken_at      timestamptz NOT NULL,
  node_count    integer NOT NULL CHECK (node_count >= 0),
  content_hash  text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE argos.inventory_snapshot_nodes (
  snapshot_id     uuid NOT NULL REFERENCES argos.inventory_snapshots(id),
  node_key        text NOT NULL,
  label           text NOT NULL,
  name            text,
  qualified_name  text,
  system_id       text,
  categories      jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (snapshot_id, node_key)
);

CREATE FUNCTION argos.inventory_snapshot_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'inventory snapshots are immutable (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER inventory_snapshots_immutable
  BEFORE UPDATE OR DELETE ON argos.inventory_snapshots
  FOR EACH ROW EXECUTE FUNCTION argos.inventory_snapshot_immutable();
CREATE TRIGGER inventory_snapshots_no_truncate
  BEFORE TRUNCATE ON argos.inventory_snapshots
  FOR EACH STATEMENT EXECUTE FUNCTION argos.inventory_snapshot_immutable();
CREATE TRIGGER inventory_snapshot_nodes_immutable
  BEFORE UPDATE OR DELETE ON argos.inventory_snapshot_nodes
  FOR EACH ROW EXECUTE FUNCTION argos.inventory_snapshot_immutable();
CREATE TRIGGER inventory_snapshot_nodes_no_truncate
  BEFORE TRUNCATE ON argos.inventory_snapshot_nodes
  FOR EACH STATEMENT EXECUTE FUNCTION argos.inventory_snapshot_immutable();
