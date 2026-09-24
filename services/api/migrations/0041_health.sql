-- ARG-094 · the domain health service: its role and the facts it publishes (F10-02).
--
-- `svc_health` reads what it measures and writes only its own observations. It verifies the
-- journal and the security log with their verifiers (it reads both), counts the queues, the gates,
-- the circuits and the periodic jobs, and records in `argos.health_facts` the facts that only it
-- can observe: the WORM canary, the certificates about to expire and the stalled queues.
--
-- `argos_facts.compute()` (F10-01) answers them to the self-* challenges, but only while they are
-- fresh: an observation older than 15 minutes means the health service stopped looking, and the
-- fact is then false. A silent monitor must not read as a healthy appliance.
--
-- The journal and the security log are now verified by the health service with their Python
-- verifiers (the same that anchor the evidence), and the view reads that result. Recomputing the
-- chains in SQL (0040) took 11 s over 27 000 entries of the development journal: the hash function
-- has a fixed search_path, so PostgreSQL calls it once per row instead of inlining it, and the
-- latency circuit of the connector opened on the self-check.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_health') THEN
    CREATE ROLE svc_health NOLOGIN;
  END IF;
END $$;
GRANT svc_health TO vault_admin WITH ADMIN OPTION;

CREATE TABLE argos.health_facts (
  fact         text PRIMARY KEY CHECK (fact ~ '^[a-z0-9_]+$'),
  setting      text NOT NULL,
  observed_at  timestamptz NOT NULL
);
REVOKE ALL ON argos.health_facts FROM PUBLIC;

GRANT USAGE ON SCHEMA argos TO svc_health;
GRANT USAGE ON SCHEMA security TO svc_health;
GRANT SELECT ON argos.audit_journal, security.events, argos.campaigns, argos.approval_requests,
                argos.approvals, argos.load_budget, argos.systems, argos.tsa_queue,
                argos.webhook_deliveries, argos.review_queue, argos.restore_tests,
                argos.ai_calibration, argos.scan_runs
   TO svc_health;
GRANT SELECT, INSERT, UPDATE ON argos.health_facts TO svc_health;

-- Whether the health service observed `fact` equal to `expected` in the last 15 minutes.
CREATE FUNCTION argos_facts.fresh(p_fact text, p_expected text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  SELECT coalesce((SELECT setting = p_expected AND observed_at > now() - interval '15 minutes'
                   FROM argos.health_facts WHERE fact = p_fact), false)
$$;
REVOKE ALL ON FUNCTION argos_facts.fresh(text, text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION argos_facts.compute() RETURNS TABLE (fact text, setting text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
WITH last_restore AS (
  SELECT result, tested_at FROM argos.restore_tests ORDER BY tested_at DESC, id DESC LIMIT 1
)
SELECT 'journal_tail_intact', argos_facts.fresh('journal_intact', '1')::text
UNION ALL
SELECT 'security_log_intact', argos_facts.fresh('security_log_intact', '1')::text
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
SELECT 'worm_canary_ok', argos_facts.fresh('worm_healthy', '1')::text
UNION ALL
SELECT 'certificates_valid', argos_facts.fresh('certs_expiring_7d', '0')::text
UNION ALL
SELECT 'queues_flowing', argos_facts.fresh('queues_stalled', '0')::text
UNION ALL
SELECT 'selfcheck_trap', 'tripped'
$$;

-- The view keeps its columns; only what the function answers grows.
