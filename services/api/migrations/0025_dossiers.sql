-- ARG-067 · Dossiers of each campaign.
--
-- One row per distinct dossier: its SHA-256 (the hash the credential cites), and where its JSON and
-- its PDF live in the WORM store. A campaign can have several, one per state (for instance before and
-- after its time stamp arrives); every one is kept and none changes.
CREATE TABLE argos.dossiers (
  sha256           text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  campaign_id      uuid NOT NULL REFERENCES argos.campaigns(id),
  json_key         text NOT NULL UNIQUE CHECK (json_key <> ''),
  json_version_id  text NOT NULL CHECK (json_version_id <> ''),
  pdf_key          text NOT NULL UNIQUE CHECK (pdf_key <> ''),
  pdf_version_id   text NOT NULL CHECK (pdf_version_id <> ''),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_dossiers_campaign ON argos.dossiers (campaign_id, created_at);

CREATE TRIGGER dossiers_write_once
  BEFORE UPDATE OR DELETE ON argos.dossiers
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER dossiers_no_truncate
  BEFORE TRUNCATE ON argos.dossiers
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
