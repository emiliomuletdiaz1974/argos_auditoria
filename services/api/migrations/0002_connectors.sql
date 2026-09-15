-- ARG-012 · Prior query journal of every probe sent to a customer system (ADR-0002, deviation note ARG-012)
CREATE TABLE argos.connector_queries (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  system_id     uuid NOT NULL REFERENCES argos.systems(id),
  kind          text NOT NULL CHECK (kind IN ('scan_schema','count','sample','check_config')),
  target        text NOT NULL,
  statement     text,
  params        jsonb NOT NULL DEFAULT '{}',
  stmt_hash     bytea NOT NULL CHECK (octet_length(stmt_hash) = 32),
  journal_seq   bigint NOT NULL UNIQUE,          -- logical FK to audit_journal.seq
  status        text NOT NULL DEFAULT 'emitted'
                CHECK (status IN ('emitted','completed','failed','rejected')),
  emitted_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  ok            boolean,
  duration_ms   integer,
  rows_touched  bigint,
  error         text
);
CREATE INDEX connector_queries_system_idx ON argos.connector_queries (system_id, emitted_at);
CREATE INDEX connector_queries_stmt_hash_idx ON argos.connector_queries (stmt_hash);

-- The declared query is immutable; only the closing columns can be written, and only once.
CREATE FUNCTION argos.connector_queries_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'connector_queries rows cannot be deleted';
  END IF;
  IF NEW.system_id   IS DISTINCT FROM OLD.system_id
     OR NEW.kind        IS DISTINCT FROM OLD.kind
     OR NEW.target      IS DISTINCT FROM OLD.target
     OR NEW.statement   IS DISTINCT FROM OLD.statement
     OR NEW.params      IS DISTINCT FROM OLD.params
     OR NEW.stmt_hash   IS DISTINCT FROM OLD.stmt_hash
     OR NEW.journal_seq IS DISTINCT FROM OLD.journal_seq
     OR NEW.emitted_at  IS DISTINCT FROM OLD.emitted_at THEN
    RAISE EXCEPTION 'connector_queries: only the closing columns can change';
  END IF;
  IF OLD.finished_at IS NOT NULL THEN
    RAISE EXCEPTION 'connector_queries: row % is already closed', OLD.journal_seq;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER connector_queries_guard BEFORE UPDATE OR DELETE ON argos.connector_queries
  FOR EACH ROW EXECUTE FUNCTION argos.connector_queries_guard();

REVOKE ALL ON argos.connector_queries FROM PUBLIC;
