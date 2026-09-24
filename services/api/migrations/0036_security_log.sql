-- F09-08 · the security log, apart from the functional journal (ADR-0014 point 7, DP-14, ENS op.exp.8).
--
-- The journal says what the product did; this log says who tried what: rejected tokens, refused
-- permissions, second factors asked for, uses of administration permissions, signatures that did
-- not verify. It is a chain of its own, with the algorithm of the journal v1 (ADR-0002) and its
-- own genesis, so the two can be verified apart and neither can be spliced into the other.
--
-- Written only by `security.append`, which members of `svc_security_writer` may execute; nobody
-- updates, deletes or truncates it. Only identifiers and reasons go in `detail`, never data of the
-- client: the library that writes it refuses anything but short scalars.
CREATE SCHEMA security;
REVOKE ALL ON SCHEMA security FROM PUBLIC;

CREATE TABLE security.events (
  seq            bigint PRIMARY KEY CHECK (seq > 0),
  at             timestamptz NOT NULL,
  at_canon       text NOT NULL,
  actor          text NOT NULL CHECK (actor <> ''),
  source         text NOT NULL CHECK (source <> ''),
  kind           text NOT NULL CHECK (kind ~ '^[a-z_]+(\.[a-z_]+)+$'),
  outcome        text NOT NULL CHECK (outcome IN ('refused', 'allowed', 'failed', 'succeeded')),
  detail         jsonb NOT NULL,
  payload_canon  text NOT NULL,
  prev_hash      bytea NOT NULL,
  entry_hash     bytea NOT NULL UNIQUE
);
CREATE INDEX ix_security_events_kind ON security.events (kind, outcome);
REVOKE ALL ON security.events FROM PUBLIC;

CREATE FUNCTION security.forbid() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'security.events is immutable (operation %)', TG_OP;
END $$;
CREATE TRIGGER security_no_update BEFORE UPDATE OR DELETE ON security.events
  FOR EACH ROW EXECUTE FUNCTION security.forbid();
CREATE TRIGGER security_no_truncate BEFORE TRUNCATE ON security.events
  FOR EACH STATEMENT EXECUTE FUNCTION security.forbid();

-- The payload is the canonical text of {"detail": {...}, "outcome": "...", "source": "..."}; the
-- kind travels apart, as the action of a journal entry does, so the verifier of the journal v1
-- reads this chain as it is.
CREATE FUNCTION security.append(p_actor text, p_kind text, p_payload_canon text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, security, argos AS $$
DECLARE
  v_seq      bigint;
  v_prev     bytea;
  v_at       timestamptz := clock_timestamp();
  v_at_canon text;
  v_payload  jsonb;
BEGIN
  IF p_actor IS NULL OR p_kind IS NULL OR p_payload_canon IS NULL THEN
    RAISE EXCEPTION 'security.append: null arguments';
  END IF;
  v_payload := p_payload_canon::jsonb;
  IF jsonb_typeof(v_payload) <> 'object' OR argos.journal_canon(v_payload) <> p_payload_canon THEN
    RAISE EXCEPTION 'security.append: payload is not canonical';
  END IF;
  IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v_payload) AS k)
     <> ARRAY['detail', 'outcome', 'source'] OR jsonb_typeof(v_payload -> 'detail') <> 'object' THEN
    RAISE EXCEPTION 'security.append: payload must be {detail, outcome, source}';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('security.events'));
  SELECT seq, entry_hash INTO v_seq, v_prev FROM security.events ORDER BY seq DESC LIMIT 1;
  IF NOT FOUND THEN
    v_seq := 0;
    v_prev := sha256(convert_to('ARGOS-SECURITY-GENESIS', 'UTF8'));
  END IF;
  v_seq := v_seq + 1;
  v_at_canon := to_char(v_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
  INSERT INTO security.events (seq, at, at_canon, actor, source, kind, outcome, detail,
                               payload_canon, prev_hash, entry_hash)
  VALUES (v_seq, v_at, v_at_canon, p_actor, v_payload ->> 'source', p_kind,
          v_payload ->> 'outcome', v_payload -> 'detail', p_payload_canon, v_prev,
          argos.journal_hash(v_seq, v_at_canon, p_actor, p_kind, p_payload_canon, v_prev));
  RETURN v_seq;
END $$;
REVOKE EXECUTE ON FUNCTION security.append(text, text, text) FROM PUBLIC;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_security_writer') THEN
    CREATE ROLE svc_security_writer NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA security TO svc_security_writer;
GRANT EXECUTE ON FUNCTION security.append(text, text, text) TO svc_security_writer;
-- The services that record: the API (authentication, authorisation, administration), the
-- campaign worker and the ontology (content signatures), the evidence (signatures of its own).
GRANT svc_security_writer TO svc_api, svc_challenge, svc_ontology, svc_evidence;

-- Reading it: the API, for platform_admin and read_only_auditor (security.read), and its metrics.
GRANT USAGE ON SCHEMA security TO svc_api;
GRANT SELECT ON security.events TO svc_api;
