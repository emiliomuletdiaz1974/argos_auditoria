-- QA-26 (quality review): the deltas of a scan run are computed once, in one transaction with
-- the marks they make (QA-030); and a snapshot takes nodes only in the transaction that created
-- it: an immutable snapshot is not one that grows afterwards (QA-040).
ALTER TABLE argos.scan_runs ADD COLUMN deltas_at timestamptz;

CREATE FUNCTION argos.inventory_snapshot_nodes_insert_once() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM argos.inventory_snapshots s
     WHERE s.id = NEW.snapshot_id AND s.xmin = pg_current_xact_id()::xid
  ) THEN
    RAISE EXCEPTION 'inventory snapshot % is closed: nodes are written only when it is taken',
      NEW.snapshot_id;
  END IF;
  RETURN NEW;
END
$$;

CREATE TRIGGER inventory_snapshot_nodes_insert_once
  BEFORE INSERT ON argos.inventory_snapshot_nodes
  FOR EACH ROW EXECUTE FUNCTION argos.inventory_snapshot_nodes_insert_once();
