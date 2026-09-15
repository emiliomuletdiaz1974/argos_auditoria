-- ARG-025 · Review queue of the assisted classifier: the DPO decides what a model only proposed
-- (deviation note ARG-024-025). Decided rows are final; decisions are journaled by the service.
CREATE TABLE argos.review_queue (
  node_key           text PRIMARY KEY,
  system_id          uuid NOT NULL REFERENCES argos.systems(id),
  qualified_name     text NOT NULL,
  proposed_category  text NOT NULL CHECK (proposed_category IN (
                       'personal_data', 'special_category.health', 'special_category.other',
                       'official_identifier', 'financial_data', 'contact_data', 'location_data',
                       'technical_credential', 'no_personal_data')),
  confidence         numeric(5, 4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  reason             text NOT NULL DEFAULT '',
  prompt_hash        text NOT NULL CHECK (prompt_hash ~ '^[0-9a-f]{16}$'),
  status             text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'accepted', 'rejected')),
  proposed_at        timestamptz NOT NULL,
  decided_at         timestamptz,
  decided_by         text,
  CHECK ((status = 'pending') = (decided_at IS NULL AND decided_by IS NULL))
);

CREATE INDEX ix_review_queue_pending ON argos.review_queue (system_id) WHERE status = 'pending';
