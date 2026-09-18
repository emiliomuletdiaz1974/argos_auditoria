-- ARG-064 · Signature of each campaign's Merkle root.
--
-- One row per campaign: where the signed envelope lives in the WORM store, its SHA-256, which key
-- signed it and whether that key is a development one (deviation note ARG-064-065). The time stamp
-- of ARG-065 covers this envelope, so the row is written once.
CREATE TABLE argos.campaign_signatures (
  campaign_id     uuid PRIMARY KEY REFERENCES argos.campaigns(id),
  object_key      text NOT NULL UNIQUE CHECK (object_key <> ''),
  version_id      text NOT NULL CHECK (version_id <> ''),
  sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  key_id          text NOT NULL CHECK (key_id ~ '^[0-9a-f]{32}$'),
  non_production  boolean NOT NULL,
  signed_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER campaign_signatures_write_once
  BEFORE UPDATE OR DELETE ON argos.campaign_signatures
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER campaign_signatures_no_truncate
  BEFORE TRUNCATE ON argos.campaign_signatures
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
