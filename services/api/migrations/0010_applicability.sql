-- ARG-039 · Applicability runs: which obligations apply to which inventory nodes, and why
-- (deviation note ARG-034-040). Each run keeps the ontology version, the date the obligations
-- were resolved for, the campaign scope and the full plan (obligation, asset class, selector,
-- challenge, resolved node keys), so the answer given to a supervisor can be reproduced
-- literally. Runs are written once and never changed.
CREATE TABLE argos.applicability_runs (
  id                uuid PRIMARY KEY,
  campaign_id       uuid,
  ontology_version  text NOT NULL REFERENCES argos.ontology_bundles(version),
  resolved_for      date NOT NULL,
  scope             jsonb NOT NULL,
  plan              jsonb NOT NULL,
  skipped           jsonb NOT NULL,
  pairs             integer NOT NULL CHECK (pairs >= 0),
  nodes_total       integer NOT NULL CHECK (nodes_total >= 0),
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_applicability_runs_campaign ON argos.applicability_runs (campaign_id, created_at);

CREATE FUNCTION argos.applicability_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'applicability runs are immutable (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER applicability_runs_immutable
  BEFORE UPDATE OR DELETE ON argos.applicability_runs
  FOR EACH ROW EXECUTE FUNCTION argos.applicability_immutable();
CREATE TRIGGER applicability_runs_no_truncate
  BEFORE TRUNCATE ON argos.applicability_runs
  FOR EACH STATEMENT EXECUTE FUNCTION argos.applicability_immutable();
