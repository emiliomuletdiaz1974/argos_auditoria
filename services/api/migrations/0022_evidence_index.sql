-- ARG-062 · Index of the evidence artifacts.
--
-- One row per verdict: where its artifact lives in the WORM store (key and version) and the SHA-256
-- of the whole file, which is the leaf of the campaign's Merkle tree. It lets the platform find an
-- artifact without listing the store. The artifact itself cannot change, so neither can its row.
--
-- verdict_id has no foreign key to argos.verdicts on purpose: one would make TRUNCATE of the verdicts
-- fail on the reference before their write-once trigger speaks, and that trigger is what the
-- immutability test of the verdicts checks. write_artifact reads the verdict before indexing it.
CREATE TABLE argos.evidence_index (
  verdict_id   uuid PRIMARY KEY,
  campaign_id  uuid NOT NULL REFERENCES argos.campaigns(id),
  object_key   text NOT NULL UNIQUE CHECK (object_key <> ''),
  version_id   text NOT NULL CHECK (version_id <> ''),
  sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  written_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_evidence_index_campaign ON argos.evidence_index (campaign_id, verdict_id);

CREATE TRIGGER evidence_index_write_once
  BEFORE UPDATE OR DELETE ON argos.evidence_index
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER evidence_index_no_truncate
  BEFORE TRUNCATE ON argos.evidence_index
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
