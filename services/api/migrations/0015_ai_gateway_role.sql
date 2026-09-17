-- ARG-052 · The AI role: the half of the barrier that lives in the database (F06-01).
--
-- Phase 06 promises that no path goes from the language model to the emission of a verdict. The
-- source tree is checked by a static test; this is the belt to that pair of braces: even if
-- somebody found a way around the code, the role the gateway connects with simply has no
-- privilege to touch a verdict or a finding.
--
-- What it may do is read. The report writer (ARG-057) narrates the campaign from its verdicts,
-- and the assistant (ARG-058) answers questions about the state of the findings: reading is their
-- job. Writing is not, and there is no flag to change that.
-- A role belongs to the cluster, not to the database: several ARGOS databases share one.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'argos_ai') THEN
    CREATE ROLE argos_ai NOLOGIN;
  END IF;
END $$;

-- Its own log: what the gateway writes about itself. The prompt never appears, only its hash.
CREATE TABLE argos.ai_usage (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  service       text NOT NULL,
  model         text NOT NULL,
  prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  tokens_in     integer NOT NULL CHECK (tokens_in >= 0),
  tokens_out    integer NOT NULL CHECK (tokens_out >= 0),
  duration_ms   integer,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_usage_service_day ON argos.ai_usage (service, created_at);

GRANT USAGE ON SCHEMA argos TO argos_ai;
GRANT SELECT ON ALL TABLES IN SCHEMA argos TO argos_ai;
GRANT INSERT, SELECT ON argos.ai_usage TO argos_ai;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA argos TO argos_ai;

-- Read-only by default on anything added later: a new table does not quietly become writable
-- for the gateway because somebody forgot this file.
ALTER DEFAULT PRIVILEGES IN SCHEMA argos GRANT SELECT ON TABLES TO argos_ai;
