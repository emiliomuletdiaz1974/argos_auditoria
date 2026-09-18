-- ARG-057 · Drafted texts of the campaign record, marked as generated.
--
-- Every row is a text a model drafted from structured data: the executive summary of a campaign or
-- the narrative of a finding. It is written only after its figures were verified against the data,
-- and it carries the mark the Phase 07 record shows the supervisor: `generated` and the hash of
-- the prompt that produced it. A generated text is part of the record, so it is written once: a
-- new draft is a new row, never an edit of the old one.
CREATE TABLE argos.report_texts (
  id            uuid PRIMARY KEY,
  kind          text NOT NULL CHECK (kind IN ('summary', 'finding')),
  campaign_id   uuid NOT NULL REFERENCES argos.campaigns(id),
  finding_id    uuid REFERENCES argos.findings(id),
  body          jsonb NOT NULL,
  generated     boolean NOT NULL DEFAULT true CHECK (generated),
  prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'finding') = (finding_id IS NOT NULL))
);
CREATE INDEX ix_report_texts_campaign ON argos.report_texts (campaign_id, kind);

CREATE TRIGGER report_texts_write_once
  BEFORE UPDATE OR DELETE ON argos.report_texts
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();

GRANT SELECT, INSERT ON argos.report_texts TO argos_ai;
