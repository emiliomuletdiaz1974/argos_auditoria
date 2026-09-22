-- ARG-079 · Webhooks towards the client's ITSM and the inbox of their deliveries.
--
-- A subscription says where to send, which events and with which template. Its secret is chosen by
-- the client and kept in the secret store: this table holds only the path where it lives, so no
-- dump of the database carries it. Each event becomes one delivery per subscription to it, and the
-- delivery keeps every attempt's outcome: «did it reach the ServiceNow?» is answered from here.
CREATE TABLE argos.webhooks (
  id          uuid PRIMARY KEY,
  url         text NOT NULL CHECK (url ~ '^https?://'),
  events      text[] NOT NULL CHECK (cardinality(events) > 0),
  template    text NOT NULL CHECK (template <> ''),
  secret_ref  text NOT NULL CHECK (secret_ref <> ''),
  created_by  text NOT NULL CHECK (created_by <> ''),
  created_at  timestamptz NOT NULL DEFAULT now(),
  active      boolean NOT NULL DEFAULT true
);
CREATE INDEX ix_webhooks_events ON argos.webhooks USING gin (events) WHERE active;

CREATE TABLE argos.webhook_deliveries (
  id                uuid PRIMARY KEY,
  webhook_id        uuid NOT NULL REFERENCES argos.webhooks(id),
  event_type        text NOT NULL CHECK (event_type <> ''),
  event             jsonb NOT NULL,
  status            text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'retrying', 'delivered', 'failed')),
  attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_status_code  integer,
  last_error        text,
  last_at           timestamptz,
  delivered_at      timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_webhook_deliveries_webhook ON argos.webhook_deliveries (webhook_id, created_at);
