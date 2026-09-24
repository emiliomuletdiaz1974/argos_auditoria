-- ARG-100 · the facts ARGOS publishes about itself, for its self-* challenges (F10-01).
--
-- ARGOS verifies ARGOS with its own engine: the self-* challenges are configuration checks of the
-- SQL connector against the appliance's database. A configuration check reads only catalogue and
-- configuration sources (SEC-022), so the appliance answers through one view of `(fact, setting)`
-- rows in its own schema, `argos_facts`, which the connector accepts as a configuration source.
--
-- The facts are computed by one SECURITY DEFINER function with a fixed search_path, and the view
-- reads it: `svc_selfcheck` may read the view and run that function, and nothing else (no table,
-- no other function, not even the schema `argos`). Every fact is computed when it is read, never
-- stored:
--
--   journal_tail_intact     the last 100 000 entries of the journal link and recompute, with the
--                           same argos.journal_hash the journal v1 writes with (ADR-0002)
--   security_log_intact     the same over the last 100 000 events of the security log (F09-08)
--   restore_test_recent     the last restore test passed and is less than 35 days old (ARG-089)
--   connections_encrypted   no connection over the network without TLS (ARG-083)
--   signed_content_in_force a signed content bundle is in force today (ARG-040, SEC-011)
--   selfcheck_trap          always 'tripped': the trap challenge self-099 fails on it, so a
--                           campaign without its finding did not really evaluate (ARG-100)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_selfcheck') THEN
    CREATE ROLE svc_selfcheck NOLOGIN;
  END IF;
END $$;

CREATE SCHEMA argos_facts;
REVOKE ALL ON SCHEMA argos_facts FROM PUBLIC;

CREATE FUNCTION argos_facts.compute() RETURNS TABLE (fact text, setting text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
WITH journal_tail AS (
  SELECT seq, prev_hash, entry_hash,
         argos.journal_hash(seq, at_canon, actor, action, payload_canon, prev_hash) AS recomputed,
         lag(seq) OVER (ORDER BY seq) AS prev_seq,
         lag(entry_hash) OVER (ORDER BY seq) AS prev_entry
  FROM argos.audit_journal
  WHERE seq >= (SELECT coalesce(max(seq), 0) - 100000 FROM argos.audit_journal)
),
security_tail AS (
  SELECT seq, prev_hash, entry_hash,
         argos.journal_hash(seq, at_canon, actor, kind, payload_canon, prev_hash) AS recomputed,
         lag(seq) OVER (ORDER BY seq) AS prev_seq,
         lag(entry_hash) OVER (ORDER BY seq) AS prev_entry
  FROM security.events
  WHERE seq >= (SELECT coalesce(max(seq), 0) - 100000 FROM security.events)
),
last_restore AS (
  SELECT result, tested_at FROM argos.restore_tests ORDER BY tested_at DESC, id DESC LIMIT 1
)
SELECT 'journal_tail_intact',
       (NOT EXISTS (
          SELECT 1 FROM journal_tail
          WHERE recomputed IS DISTINCT FROM entry_hash
             OR (prev_seq IS NOT NULL
                 AND (seq <> prev_seq + 1 OR prev_hash IS DISTINCT FROM prev_entry))
             OR (seq = 1 AND prev_hash <> sha256(convert_to('ARGOS-GENESIS', 'UTF8')))
        ))::text
UNION ALL
SELECT 'security_log_intact',
       (NOT EXISTS (
          SELECT 1 FROM security_tail
          WHERE recomputed IS DISTINCT FROM entry_hash
             OR (prev_seq IS NOT NULL
                 AND (seq <> prev_seq + 1 OR prev_hash IS DISTINCT FROM prev_entry))
             OR (seq = 1 AND prev_hash <> sha256(convert_to('ARGOS-SECURITY-GENESIS', 'UTF8')))
        ))::text
UNION ALL
SELECT 'restore_test_recent',
       coalesce((SELECT result = 'passed' AND tested_at > now() - interval '35 days'
                 FROM last_restore), false)::text
UNION ALL
SELECT 'connections_encrypted',
       (NOT EXISTS (
          SELECT 1 FROM pg_stat_activity a JOIN pg_stat_ssl s ON s.pid = a.pid
          WHERE a.client_addr IS NOT NULL AND NOT s.ssl
        ))::text
UNION ALL
SELECT 'signed_content_in_force',
       (EXISTS (
          SELECT 1 FROM argos.ontology_bundles
          WHERE in_force_from <= current_date AND octet_length(signature) > 0
        ))::text
UNION ALL
SELECT 'selfcheck_trap', 'tripped'
$$;
REVOKE ALL ON FUNCTION argos_facts.compute() FROM PUBLIC;

CREATE VIEW argos_facts.facts (fact, setting) AS SELECT fact, setting FROM argos_facts.compute();

REVOKE ALL ON argos_facts.facts FROM PUBLIC;
GRANT USAGE ON SCHEMA argos_facts TO svc_selfcheck;
GRANT SELECT ON argos_facts.facts TO svc_selfcheck;
-- Functions in a view run with the reader's rights: the one that computes the facts, nothing else.
GRANT EXECUTE ON FUNCTION argos_facts.compute() TO svc_selfcheck;
