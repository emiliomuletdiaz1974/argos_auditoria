-- ARG-092/099 · the alerts Alertmanager delivers to the API, for the operation screen (F10-07).
--
-- One row per alert (its fingerprint), kept up to date on each delivery: `firing` while it lasts,
-- `resolved` when Alertmanager says so. Every replica of the API reads the same table. The API
-- is the only service that writes it.
CREATE TABLE argos.operation_alerts (
  fingerprint  text PRIMARY KEY CHECK (fingerprint <> '' AND length(fingerprint) <= 64),
  alertname    text NOT NULL,
  severity     text NOT NULL,
  status       text NOT NULL CHECK (status IN ('firing', 'resolved')),
  summary      text NOT NULL,
  runbook      text CHECK (runbook ~ '^RB-[0-9]{2}-[a-z0-9-]+$'),
  labels       jsonb NOT NULL DEFAULT '{}',
  starts_at    timestamptz,
  updated_at   timestamptz NOT NULL
);
CREATE INDEX ix_operation_alerts_firing ON argos.operation_alerts (status) WHERE status = 'firing';

REVOKE ALL ON argos.operation_alerts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON argos.operation_alerts TO svc_api;
