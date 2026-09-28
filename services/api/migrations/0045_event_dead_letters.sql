-- QA-25 (QA-001, quality review): an event whose handler failed on every delivery is kept here
-- instead of being dropped by JetStream. The subscribers write, the health service counts the
-- open ones (`argos_events_dead_letters`) and `EventsDeadLettered` makes them seen. An operator
-- marks one resolved once the cause is fixed and the event replayed (RB-05).
CREATE TABLE argos.event_dead_letters (
  id          bigserial PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  service     text NOT NULL,
  subject     text NOT NULL,
  durable     text NOT NULL,
  event_id    text NOT NULL,
  event       jsonb NOT NULL,
  error       text NOT NULL,
  deliveries  integer NOT NULL CHECK (deliveries > 0),
  resolved_at timestamptz
);
CREATE INDEX ix_event_dead_letters_open ON argos.event_dead_letters (durable) WHERE resolved_at IS NULL;

REVOKE ALL ON argos.event_dead_letters FROM PUBLIC;
GRANT INSERT ON argos.event_dead_letters TO svc_inventory, svc_challenge, svc_evidence, svc_webhook;
GRANT USAGE ON SEQUENCE argos.event_dead_letters_id_seq TO svc_inventory, svc_challenge, svc_evidence, svc_webhook;
GRANT SELECT ON argos.event_dead_letters TO svc_health;
