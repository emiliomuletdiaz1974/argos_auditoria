-- ARG-048 · Findings: a non-conformity with an owner, a severity and a way out.
-- A finding is not a log line. It is deduplicated by fingerprint (challenge + node), so successive
-- campaigns do not multiply it: a recurrence raises the counter and, from three campaigns, the
-- severity. Accepting the risk is a documented exception with an expiry, never a silent drawer.
CREATE TABLE argos.findings (
  id             uuid PRIMARY KEY,
  fingerprint    text NOT NULL UNIQUE,
  campaign_id    uuid NOT NULL REFERENCES argos.campaigns(id),
  challenge_id   text NOT NULL,
  obligation     text NOT NULL,
  system_id      uuid NOT NULL,
  node_key       text NOT NULL,
  severity       text NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
  status         text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'in_remediation', 'pending_verification',
                                   'closed_compliant', 'reopened', 'risk_accepted')),
  occurrences    integer NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
  campaigns_seen text[] NOT NULL DEFAULT '{}',
  last_verdict   uuid,
  detail         jsonb NOT NULL DEFAULT '{}',
  risk_note      text,
  risk_expiry    date,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT risk_accepted_is_documented
    CHECK (status <> 'risk_accepted' OR (risk_note IS NOT NULL AND risk_expiry IS NOT NULL))
);
CREATE INDEX ix_findings_status ON argos.findings (status, severity);
CREATE INDEX ix_findings_campaign ON argos.findings (campaign_id);
