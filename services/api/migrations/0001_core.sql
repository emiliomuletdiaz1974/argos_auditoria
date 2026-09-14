-- ARG-005 · Core schema and chained journal v1 (ADR-0002, deviation note ARG-005)
CREATE SCHEMA IF NOT EXISTS argos;

CREATE TABLE IF NOT EXISTS argos.schema_version (
  version     integer PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now(),
  checksum    text NOT NULL
);

CREATE TABLE argos.settings (
  key         text PRIMARY KEY,
  value       jsonb NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Customer systems registered for verification (populated by C1/C2). UUID v7 ids come from the application.
CREATE TABLE argos.systems (
  id                     uuid PRIMARY KEY,
  name                   text NOT NULL,
  kind                   text NOT NULL CHECK (kind IN ('rdbms','files','api','directory','clinical','ai','other')),
  environment            text NOT NULL DEFAULT 'production',
  owner                  text,
  connection             jsonb NOT NULL,          -- secret reference, never the credential itself
  read_only_verified_at  timestamptz,             -- no-write proof (P-04)
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE argos.campaigns (
  id          uuid PRIMARY KEY,
  name        text NOT NULL,
  status      text NOT NULL DEFAULT 'draft'
              CHECK (status IN ('draft','approved','running','in_review','closed')),
  scope       jsonb NOT NULL,
  windows     jsonb NOT NULL DEFAULT '[]',
  created_by  text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  closed_at   timestamptz
);

-- ── Chained audit journal v1: insert-only through journal_append ──
CREATE TABLE argos.audit_journal (
  seq            bigint PRIMARY KEY CHECK (seq >= 1),
  at             timestamptz NOT NULL,
  at_canon       text NOT NULL,
  actor          text NOT NULL,
  action         text NOT NULL,
  payload        jsonb NOT NULL,
  payload_canon  text NOT NULL,
  prev_hash      bytea NOT NULL CHECK (octet_length(prev_hash) = 32),
  entry_hash     bytea NOT NULL UNIQUE CHECK (octet_length(entry_hash) = 32)
);
CREATE INDEX audit_journal_action_idx ON argos.audit_journal (action);
CREATE INDEX audit_journal_at_idx ON argos.audit_journal (at);

CREATE FUNCTION argos.journal_forbid() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_journal is immutable (operation %)', TG_OP;
END $$;

CREATE TRIGGER journal_no_update BEFORE UPDATE OR DELETE ON argos.audit_journal
  FOR EACH ROW EXECUTE FUNCTION argos.journal_forbid();
CREATE TRIGGER journal_no_truncate BEFORE TRUNCATE ON argos.audit_journal
  FOR EACH STATEMENT EXECUTE FUNCTION argos.journal_forbid();

-- lp(x) = u32be(length in bytes) ‖ UTF-8(x)
CREATE FUNCTION argos.journal_lp(t text) RETURNS bytea
LANGUAGE sql IMMUTABLE STRICT SET search_path = pg_catalog AS $$
  SELECT int4send(octet_length(convert_to(t, 'UTF8'))) || convert_to(t, 'UTF8')
$$;

-- Pure entry hash; must match argos_common.journal.compute_hash
CREATE FUNCTION argos.journal_hash(
  p_seq bigint, p_at_canon text, p_actor text, p_action text, p_payload_canon text, p_prev bytea
) RETURNS bytea
LANGUAGE sql IMMUTABLE STRICT SET search_path = pg_catalog, argos AS $$
  SELECT sha256(convert_to('ARGOS-JOURNAL-v1', 'UTF8') || int8send(p_seq)
                || argos.journal_lp(p_at_canon) || argos.journal_lp(p_actor)
                || argos.journal_lp(p_action) || argos.journal_lp(p_payload_canon) || p_prev)
$$;

CREATE FUNCTION argos.journal_append(p_actor text, p_action text, p_payload_canon text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, argos AS $$
DECLARE
  v_seq       bigint;
  v_prev      bytea;
  v_at        timestamptz := clock_timestamp();
  v_at_canon  text;
BEGIN
  IF p_actor IS NULL OR p_action IS NULL OR p_payload_canon IS NULL THEN
    RAISE EXCEPTION 'journal_append: null arguments';
  END IF;
  -- Serialize every writer: without this, two transactions would link to the same head
  PERFORM pg_advisory_xact_lock(hashtext('argos.audit_journal'));
  SELECT seq, entry_hash INTO v_seq, v_prev FROM argos.audit_journal ORDER BY seq DESC LIMIT 1;
  IF NOT FOUND THEN
    v_seq := 0;
    v_prev := sha256(convert_to('ARGOS-GENESIS', 'UTF8'));
  END IF;
  v_seq := v_seq + 1;
  v_at_canon := to_char(v_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
  INSERT INTO argos.audit_journal (seq, at, at_canon, actor, action, payload, payload_canon, prev_hash, entry_hash)
  VALUES (v_seq, v_at, v_at_canon, p_actor, p_action, p_payload_canon::jsonb, p_payload_canon, v_prev,
          argos.journal_hash(v_seq, v_at_canon, p_actor, p_action, p_payload_canon, v_prev));
  RETURN v_seq;
END $$;

REVOKE ALL ON argos.audit_journal FROM PUBLIC;
REVOKE ALL ON FUNCTION argos.journal_append(text, text, text) FROM PUBLIC;
