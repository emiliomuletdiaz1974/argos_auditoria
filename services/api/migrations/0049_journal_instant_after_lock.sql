-- QA-34 (quality review QA-012): `journal_append` and `security.append` took the instant before
-- waiting for the lock of their chain, so an entry that waited could carry an earlier `at` than the
-- one written before it. Both are the same functions as before, with the instant taken once the
-- lock is held. CREATE OR REPLACE keeps their owners and grants.

CREATE OR REPLACE FUNCTION argos.journal_append(p_actor text, p_action text, p_payload_canon text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, argos AS $$
DECLARE
  v_seq       bigint;
  v_prev      bytea;
  v_at        timestamptz;
  v_at_canon  text;
  v_payload   jsonb;
BEGIN
  IF p_actor IS NULL OR p_action IS NULL OR p_payload_canon IS NULL THEN
    RAISE EXCEPTION 'journal_append: null arguments';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = session_user AND rolsuper)
     AND NOT EXISTS (
       SELECT 1 FROM argos.journal_grants g
        WHERE pg_has_role(session_user, g.role_name, 'MEMBER')
          AND p_actor LIKE g.actor_pattern
          AND p_action LIKE g.action_pattern)
  THEN
    RAISE EXCEPTION USING
      ERRCODE = 'insufficient_privilege',
      MESSAGE = format('journal_append: %s may not write %s as %s', session_user, p_action, p_actor);
  END IF;
  v_payload := p_payload_canon::jsonb;
  IF jsonb_typeof(v_payload) <> 'object' OR argos.journal_canon(v_payload) <> p_payload_canon THEN
    RAISE EXCEPTION 'journal_append: payload is not canonical';
  END IF;
  -- Serialize every writer: without this, two transactions would link to the same head
  PERFORM pg_advisory_xact_lock(hashtext('argos.audit_journal'));
  -- The instant is taken with the lock held: the order by time is the order by sequence.
  v_at := clock_timestamp();
  SELECT seq, entry_hash INTO v_seq, v_prev FROM argos.audit_journal ORDER BY seq DESC LIMIT 1;
  IF NOT FOUND THEN
    v_seq := 0;
    v_prev := sha256(convert_to('ARGOS-GENESIS', 'UTF8'));
  END IF;
  v_seq := v_seq + 1;
  v_at_canon := to_char(v_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
  INSERT INTO argos.audit_journal (seq, at, at_canon, actor, action, payload, payload_canon, prev_hash, entry_hash)
  VALUES (v_seq, v_at, v_at_canon, p_actor, p_action, v_payload, p_payload_canon, v_prev,
          argos.journal_hash(v_seq, v_at_canon, p_actor, p_action, p_payload_canon, v_prev));
  RETURN v_seq;
END $$;

CREATE OR REPLACE FUNCTION security.append(p_actor text, p_kind text, p_payload_canon text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, security, argos AS $$
DECLARE
  v_seq      bigint;
  v_prev     bytea;
  v_at       timestamptz;
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
  -- The instant is taken with the lock held: the order by time is the order by sequence.
  v_at := clock_timestamp();
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
