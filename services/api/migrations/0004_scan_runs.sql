-- ARG-022/023 · Discovery scan runs: the time cuts of the inventory (deviation note ARG-021-023)
CREATE TABLE argos.scan_runs (
  id           uuid PRIMARY KEY,
  system_id    uuid NOT NULL REFERENCES argos.systems(id),
  status       text NOT NULL DEFAULT 'running'
               CHECK (status IN ('running', 'completed', 'failed')),
  started_at   timestamptz NOT NULL,
  finished_at  timestamptz,
  events       integer NOT NULL DEFAULT 0 CHECK (events >= 0),
  prev_run     uuid REFERENCES argos.scan_runs(id),
  error        text,
  CHECK ((status = 'running') = (finished_at IS NULL))
);

CREATE INDEX ix_scan_runs_system_started ON argos.scan_runs (system_id, started_at DESC);
