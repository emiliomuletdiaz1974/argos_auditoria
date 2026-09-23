-- ARG-005 · ADR-0002 · the journal admits from each role only its own entries, in canonical form.
--
-- Security review F09-02, SEC-017. `journal_append` took any actor and any action from whoever
-- could execute it, the AI gateway included, and stored the text it was given as it came: with a
-- duplicated key, the hash covered one payload and `jsonb` kept another.
--
-- Two checks, before anything is written:
--   * the payload must be the canonical text of ADR-0002 (keys sorted by code point, no spaces,
--     integers only). The engine rebuilds it from the parsed value and refuses what differs;
--   * a service role writes only the actors and actions of `argos.journal_grants`. The login user
--     of the session (`session_user`) is what counts: inside a SECURITY DEFINER function
--     `current_user` is the owner. A superuser session is not restricted, because it could write
--     the table directly anyway: migrations and the tests of the product connect that way.
--
-- The hash formula does not change: every entry already written verifies as before.

CREATE FUNCTION argos.journal_canon(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog, argos AS $$
DECLARE
  kind text := jsonb_typeof(v);
  result text;
BEGIN
  IF kind = 'object' THEN
    -- COLLATE "C" orders UTF-8 by bytes, which is the order of code points: Python's sort_keys.
    SELECT '{' || coalesce(string_agg(to_json(key)::text || ':' || argos.journal_canon(value), ','
                                      ORDER BY key COLLATE "C"), '') || '}'
      INTO result FROM jsonb_each(v);
    RETURN result;
  ELSIF kind = 'array' THEN
    SELECT '[' || coalesce(string_agg(argos.journal_canon(item), ',' ORDER BY n), '') || ']'
      INTO result FROM jsonb_array_elements(v) WITH ORDINALITY AS a(item, n);
    RETURN result;
  ELSIF kind = 'string' THEN
    RETURN to_json(v #>> '{}')::text;
  ELSIF kind = 'number' THEN
    IF v::text !~ '^(0|-?[1-9][0-9]*)$' THEN
      RAISE EXCEPTION 'journal_append: payload is not canonical: only integers are allowed';
    END IF;
    RETURN v::text;
  END IF;
  RETURN v::text;  -- true, false, null
END $$;

-- Who may write what. Patterns are LIKE patterns: '%' is any text; an actor without '%' is that
-- actor exactly, so `system:ai-gateway` does not admit `system:ai-gateway-x`.
CREATE TABLE argos.journal_grants (
  role_name       name NOT NULL,
  actor_pattern   text NOT NULL CHECK (actor_pattern <> ''),
  action_pattern  text NOT NULL CHECK (action_pattern <> ''),
  reason          text NOT NULL CHECK (reason <> ''),
  PRIMARY KEY (role_name, actor_pattern, action_pattern)
);
REVOKE ALL ON argos.journal_grants FROM PUBLIC;

INSERT INTO argos.journal_grants (role_name, actor_pattern, action_pattern, reason) VALUES
  -- The API acts for the people who call it, and runs the domain functions that record the system.
  ('svc_api',        'user:%',                       '%',        'what a person did through the API'),
  ('svc_api',        'system:%',                     '%',        'domain functions the API runs'),
  -- The campaign worker records the campaign, its probes, verdicts, findings and seal.
  ('svc_challenge',  'system:%',                     '%',        'the campaign and its probes'),
  ('svc_evidence',   'system:evidence',              '%',        'signing, stamping and issuing'),
  ('svc_inventory',  'system:%',                     '%',        'exploration, deltas and snapshots'),
  ('svc_ontology',   'system:ontology',              '%',        'loading signed bundles'),
  ('svc_ontology',   'system:resolver',              '%',        'applicability resolution'),
  -- The gateway writes as itself and only its own acts (SEC-017).
  ('svc_ai_gateway', 'system:ai-gateway',            'ai.%',     'completions of the AI gateway'),
  ('svc_webhook',    'system:argos-webhook-worker',  'webhook.%', 'deliveries of the webhook worker'),
  ('svc_example',    'system:argos-example',         'demo.%',   'the example service'),
  ('svc_migrator',   'system:migrator',              'schema.%', 'applied migrations');

CREATE OR REPLACE FUNCTION argos.journal_append(p_actor text, p_action text, p_payload_canon text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, argos AS $$
DECLARE
  v_seq       bigint;
  v_prev      bytea;
  v_at        timestamptz := clock_timestamp();
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

REVOKE EXECUTE ON FUNCTION argos.journal_canon(jsonb) FROM PUBLIC;

-- SEC-029, SEC-040: the API reserves an idempotency key before it runs the request, and frees it
-- when the request fails. A reservation has no answer yet.
ALTER TABLE argos.api_idempotency ALTER COLUMN status_code DROP NOT NULL;
GRANT UPDATE, DELETE ON argos.api_idempotency TO svc_api;
