-- ARG-043/046/047 · Campaigns (extended), work units, verdicts and human gates.
-- A campaign pins what it measured against (snapshot, ontology version and library version), so two
-- runs of the same campaign are comparable. Verdicts and approvals are written once and never change:
-- the file handed to a supervisor is read from these tables.
-- `argos.campaigns` already exists since the core migration of Phase 01 (name, status, scope,
-- windows, created_by). Nothing uses it yet, so here it grows what a campaign of Phase 05 pins and
-- its states become the ones of the engine.
ALTER TABLE argos.campaigns
  ADD COLUMN snapshot_id       uuid,
  ADD COLUMN snapshot_hash     text,
  ADD COLUMN ontology_version  text,
  ADD COLUMN library_version   text,
  ADD COLUMN library_sha256    text,
  ADD COLUMN applicability_run uuid,
  ADD COLUMN sealed_at         timestamptz,
  ADD COLUMN seal              text;

ALTER TABLE argos.campaigns DROP CONSTRAINT campaigns_status_check;
ALTER TABLE argos.campaigns ALTER COLUMN status SET DEFAULT 'planned';
ALTER TABLE argos.campaigns ADD CONSTRAINT campaigns_status_check
  CHECK (status IN ('planned', 'pinned', 'running', 'sealed', 'failed'));

CREATE INDEX ix_campaigns_status ON argos.campaigns (status, created_at);

-- The compiled unit, inert and complete: the remediation of a finding re-runs exactly this.
CREATE TABLE argos.campaign_units (
  campaign_id  uuid NOT NULL REFERENCES argos.campaigns(id),
  unit_id      text NOT NULL,
  unit         jsonb NOT NULL,
  status       text NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'done', 'frozen')),
  PRIMARY KEY (campaign_id, unit_id)
);

CREATE TABLE argos.verdicts (
  id                 uuid PRIMARY KEY,
  campaign_id        uuid NOT NULL REFERENCES argos.campaigns(id),
  unit_id            text NOT NULL,
  challenge_id       text NOT NULL,
  challenge_version  text NOT NULL,
  obligation         text NOT NULL,
  system_id          uuid NOT NULL,
  node_key           text NOT NULL,
  result             text NOT NULL
                     CHECK (result IN ('compliant', 'non_compliant', 'not_demonstrated',
                                       'inconclusive')),
  verdict            jsonb NOT NULL,
  verdict_hash       text NOT NULL,
  probe_journal_seq  bigint,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, unit_id)
);
CREATE INDEX ix_verdicts_campaign_result ON argos.verdicts (campaign_id, result);

CREATE TABLE argos.approval_requests (
  campaign_id   uuid NOT NULL REFERENCES argos.campaigns(id),
  gate          text NOT NULL,
  payload       jsonb NOT NULL,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, gate)
);

CREATE TABLE argos.approvals (
  campaign_id  uuid NOT NULL,
  gate         text NOT NULL,
  approved_by  text NOT NULL,
  approved_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, gate, approved_by),
  FOREIGN KEY (campaign_id, gate) REFERENCES argos.approval_requests(campaign_id, gate)
);

CREATE FUNCTION argos.campaign_write_once() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'this record is written once (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER verdicts_write_once
  BEFORE UPDATE OR DELETE ON argos.verdicts
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER verdicts_no_truncate
  BEFORE TRUNCATE ON argos.verdicts
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER approvals_write_once
  BEFORE UPDATE OR DELETE ON argos.approvals
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER approval_requests_write_once
  BEFORE UPDATE OR DELETE ON argos.approval_requests
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
