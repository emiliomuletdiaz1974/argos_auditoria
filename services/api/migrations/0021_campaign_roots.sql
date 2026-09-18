-- ARG-063 · Merkle root of each campaign's evidence.
--
-- One row per campaign: the root over the SHA-256 of its artifacts, how many leaves it has, the
-- order of those leaves (ascending verdict_id) and the WORM key of the full tree. The root is what
-- the signature (ARG-064) and the time stamp (ARG-065) cover, so it is written once.
CREATE TABLE argos.campaign_roots (
  campaign_id  uuid PRIMARY KEY REFERENCES argos.campaigns(id),
  root         text NOT NULL CHECK (root ~ '^[0-9a-f]{64}$'),
  leaf_count   integer NOT NULL CHECK (leaf_count > 0),
  leaf_order   text NOT NULL DEFAULT 'verdict_id' CHECK (leaf_order = 'verdict_id'),
  tree_key     text NOT NULL CHECK (tree_key <> ''),
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER campaign_roots_write_once
  BEFORE UPDATE OR DELETE ON argos.campaign_roots
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER campaign_roots_no_truncate
  BEFORE TRUNCATE ON argos.campaign_roots
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
