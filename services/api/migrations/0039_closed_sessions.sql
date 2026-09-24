-- F09-32 (SEC-060) · sessions closed before their access tokens expire.
--
-- The API validates access tokens without state. When a person closes the session, the realm
-- revokes its refresh token and the API records the session (`sid`) here until no token of it can
-- still be valid; the guard of every replica refuses a token whose session is in this table.
-- Rows past their `closed_until` are worth nothing and the API deletes them as it writes.
CREATE TABLE argos.closed_sessions (
  sid           text PRIMARY KEY CHECK (sid <> '' AND length(sid) <= 128),
  closed_at     timestamptz NOT NULL DEFAULT now(),
  closed_until  timestamptz NOT NULL
);
CREATE INDEX ix_closed_sessions_until ON argos.closed_sessions (closed_until);

REVOKE ALL ON argos.closed_sessions FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON argos.closed_sessions TO svc_api;
