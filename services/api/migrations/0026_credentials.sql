-- ARG-068 · Verifiable credentials of the campaigns and their revocations.
--
-- One credential per dossier: where it lives in the WORM store and its place in the Bitstring Status
-- List (list number and index, drawn from a sequence so no two credentials share a bit). Revoking a
-- credential does not touch it: a row is added to argos.credential_revocations, and the status list
-- is rebuilt from those rows and signed again. Both tables are written once.
CREATE SEQUENCE argos.credential_status_seq MINVALUE 0 START 0;

CREATE TABLE argos.credentials (
  id              text PRIMARY KEY CHECK (id LIKE 'urn:uuid:%'),
  campaign_id     uuid NOT NULL REFERENCES argos.campaigns(id),
  dossier_sha256  text NOT NULL UNIQUE REFERENCES argos.dossiers(sha256),
  status_list     integer NOT NULL CHECK (status_list >= 0),
  status_index    integer NOT NULL CHECK (status_index >= 0 AND status_index < 131072),
  object_key      text NOT NULL UNIQUE CHECK (object_key <> ''),
  version_id      text NOT NULL CHECK (version_id <> ''),
  sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  issued_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (status_list, status_index)
);
CREATE INDEX ix_credentials_campaign ON argos.credentials (campaign_id);

CREATE TABLE argos.credential_revocations (
  credential_id  text PRIMARY KEY REFERENCES argos.credentials(id),
  reason         text NOT NULL CHECK (reason <> ''),
  revoked_by     text NOT NULL CHECK (revoked_by <> ''),
  revoked_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER credentials_write_once
  BEFORE UPDATE OR DELETE ON argos.credentials
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER credentials_no_truncate
  BEFORE TRUNCATE ON argos.credentials
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER credential_revocations_write_once
  BEFORE UPDATE OR DELETE ON argos.credential_revocations
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER credential_revocations_no_truncate
  BEFORE TRUNCATE ON argos.credential_revocations
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
