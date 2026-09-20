-- ARG-071 · What the API already answered for an idempotency key.
--
-- A client that retries a creation —because the network dropped, not because it changed its mind—
-- must get the first answer again, not a second campaign. The row keeps the fingerprint of the
-- request so the same key with a different body is a conflict and not a silent replay, and the
-- answer that was given, so the retry costs nothing.
--
-- This is operational state, not evidence: it is written once, read on retries and pruned by
-- retention. What the mutation did lives in the journal, which is the one that is chained.
CREATE TABLE argos.api_idempotency (
  actor           text NOT NULL CHECK (actor <> ''),
  key             text NOT NULL CHECK (key <> ''),
  method          text NOT NULL CHECK (method IN ('POST', 'PUT', 'PATCH', 'DELETE')),
  path            text NOT NULL CHECK (path <> ''),
  request_sha256  text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  status_code     integer NOT NULL CHECK (status_code BETWEEN 200 AND 299),
  response        jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (actor, key)
);
CREATE INDEX ix_api_idempotency_created ON argos.api_idempotency (created_at);
