-- ARG-052 · Daily token budget per service.
--
-- It lives in a table and not in a constant because it is an operational decision: an appliance
-- under pressure moves the nightly classification budget without a release. What does not move is
-- that the gateway reads it before calling the model, never after spending.
--
-- A service with no row here cannot spend: the default is zero, not infinite.
CREATE TABLE argos.ai_quotas (
  service      text PRIMARY KEY,
  daily_tokens bigint NOT NULL CHECK (daily_tokens >= 0),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

INSERT INTO argos.ai_quotas (service, daily_tokens) VALUES
  ('inventory',  2000000),
  ('challenge',  1000000),
  ('reports',    1000000),
  ('assistant',  3000000);

GRANT SELECT ON argos.ai_quotas TO argos_ai;
