-- ARG-070 · Credentials published in data spaces.
--
-- Publishing is optional and decided per campaign. When it happens, which credential went out, as
-- which asset, under which policy of the library and who decided it are kept here, once.
CREATE TABLE argos.dataspace_publications (
  credential_id  text NOT NULL REFERENCES argos.credentials(id),
  asset_id       text NOT NULL CHECK (asset_id <> ''),
  policy_id      text NOT NULL CHECK (policy_id <> ''),
  contract_id    text NOT NULL CHECK (contract_id <> ''),
  policy_choice  text NOT NULL CHECK (policy_choice IN ('use_only', 'no_redistribution', 'retention')),
  published_by   text NOT NULL CHECK (published_by <> ''),
  published_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (credential_id, asset_id)
);

CREATE TRIGGER dataspace_publications_write_once
  BEFORE UPDATE OR DELETE ON argos.dataspace_publications
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER dataspace_publications_no_truncate
  BEFORE TRUNCATE ON argos.dataspace_publications
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
