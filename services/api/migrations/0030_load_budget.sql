-- ARG-013 · The load budget of each customer system, shared by every process that probes it.
--
-- P-05 limits what ARGOS asks of a system, whoever asks: a campaign, a rescan and a classification
-- running at the same time share the same tokens and the same circuit breaker (security review
-- F09-02, SEC-004). One row per system, taken with SELECT … FOR UPDATE; times are the database's
-- clock, so processes on different hosts agree. Nothing here identifies a person or a datum.
CREATE TABLE argos.load_budget (
  system_id   text PRIMARY KEY CHECK (system_id <> ''),
  tokens      double precision NOT NULL CHECK (tokens >= 0),
  updated_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
  state       text NOT NULL DEFAULT 'closed' CHECK (state IN ('closed', 'open', 'half_open')),
  opened_at   timestamptz,
  trial_at    timestamptz,           -- when the half-open trial probe was handed out, if one is
  latencies   integer[] NOT NULL DEFAULT '{}'
);
