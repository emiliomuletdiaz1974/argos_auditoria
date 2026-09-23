-- ARG-085 (base) · ADR-0014 · one PostgreSQL role per service, with the least privilege (F09-04).
--
-- No service connects as the superuser any more. Each connects as a login user that is a member
-- of its NOLOGIN role (F09-05 will make those users dynamic), and the role holds exactly what the
-- access inventory of the service found (argos/.scratch/accesos-bd/, walked from the entry point
-- of every container), minus what the product forbids: only the evaluator writes a verdict and
-- nobody rewrites the journal, which is written through journal_append() alone.
--
-- Roles belong to the cluster, grants to each database: several ARGOS databases share the roles.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['svc_inventory', 'svc_ontology', 'svc_challenge', 'svc_evidence',
                          'svc_api', 'svc_ai_gateway', 'svc_webhook', 'svc_example', 'svc_migrator']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

-- Nothing for PUBLIC: every privilege below is given by name.
REVOKE ALL ON ALL TABLES IN SCHEMA argos FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA argos FROM PUBLIC;

-- The migrator creates objects; it owns nothing it did not create.
GRANT USAGE, CREATE ON SCHEMA argos TO svc_migrator;
GRANT USAGE, CREATE ON SCHEMA inventory TO svc_migrator;

-- refresh_catalog() refreshes materialized views, which only their owner may do: it now runs as
-- the owner, with a fixed search_path, and only the services that show the catalog call it.
ALTER FUNCTION argos.refresh_catalog() SECURITY DEFINER SET search_path = pg_catalog, argos;

GRANT USAGE ON SCHEMA argos TO svc_ai_gateway, svc_api, svc_challenge, svc_evidence, svc_example, svc_inventory, svc_ontology, svc_webhook;
GRANT EXECUTE ON FUNCTION argos.journal_append(text, text, text) TO svc_ai_gateway, svc_api, svc_challenge, svc_evidence, svc_example, svc_inventory, svc_ontology, svc_webhook;
GRANT EXECUTE ON FUNCTION argos.refresh_catalog() TO svc_ai_gateway, svc_api, svc_inventory;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA argos TO svc_ai_gateway, svc_api, svc_challenge, svc_evidence, svc_inventory, svc_ontology, svc_webhook;

-- svc_ai_gateway
GRANT INSERT, SELECT ON argos.ai_usage, argos.rag_chunks TO svc_ai_gateway;
GRANT SELECT ON argos.ai_quotas, argos.catalog_columns, argos.catalog_coverage, argos.catalog_freshness, argos.findings, argos.review_queue, argos.systems, argos.verdicts TO svc_ai_gateway;

-- svc_api
GRANT INSERT ON argos.applicability_runs TO svc_api;
GRANT INSERT, SELECT ON argos.api_idempotency, argos.approval_requests, argos.approvals, argos.campaign_roots, argos.campaign_signatures, argos.credential_revocations, argos.credentials, argos.dossiers, argos.evidence_index, argos.inventory_deltas, argos.inventory_snapshot_nodes, argos.inventory_snapshot_shapes_data, argos.inventory_snapshots, argos.ontology_bundles, argos.synthetic_exercises, argos.synthetic_subjects, argos.webhooks TO svc_api;
GRANT INSERT, SELECT, UPDATE ON argos.campaign_units, argos.campaigns, argos.findings, argos.load_budget, argos.review_queue, argos.synthetic_injections, argos.tsa_queue, argos.webhook_deliveries TO svc_api;
GRANT INSERT, UPDATE ON argos.connector_queries TO svc_api;
GRANT SELECT ON argos.audit_journal, argos.catalog_columns, argos.catalog_coverage, argos.catalog_freshness, argos.ontology_quads, argos.report_texts, argos.scan_runs, argos.systems, argos.verdicts TO svc_api;

-- svc_challenge
GRANT INSERT ON argos.applicability_runs TO svc_challenge;
GRANT INSERT, SELECT ON argos.approval_requests, argos.approvals, argos.inventory_deltas, argos.inventory_snapshot_nodes, argos.inventory_snapshot_shapes_data, argos.inventory_snapshots, argos.ontology_bundles, argos.synthetic_exercises, argos.synthetic_subjects, argos.verdicts TO svc_challenge;
GRANT INSERT, SELECT, UPDATE ON argos.campaign_units, argos.campaigns, argos.findings, argos.load_budget, argos.synthetic_injections TO svc_challenge;
GRANT INSERT, UPDATE ON argos.connector_queries TO svc_challenge;
GRANT SELECT ON argos.audit_journal, argos.ontology_quads, argos.scan_runs, argos.systems TO svc_challenge;

-- svc_evidence
GRANT INSERT, SELECT ON argos.campaign_roots, argos.campaign_signatures, argos.credential_revocations, argos.credentials, argos.dossiers, argos.evidence_index TO svc_evidence;
GRANT INSERT, SELECT, UPDATE ON argos.tsa_queue TO svc_evidence;
GRANT INSERT, UPDATE ON argos.connector_queries TO svc_evidence;
GRANT SELECT ON argos.approvals, argos.audit_journal, argos.campaigns, argos.findings, argos.report_texts, argos.verdicts TO svc_evidence;

-- svc_example
GRANT SELECT ON argos.audit_journal TO svc_example;

-- svc_inventory
GRANT INSERT, SELECT ON argos.inventory_deltas TO svc_inventory;
GRANT INSERT, SELECT, UPDATE ON argos.load_budget, argos.scan_runs TO svc_inventory;
GRANT INSERT, UPDATE ON argos.connector_queries TO svc_inventory;
GRANT SELECT ON argos.audit_journal, argos.catalog_columns, argos.catalog_coverage, argos.catalog_freshness, argos.review_queue, argos.systems TO svc_inventory;

-- svc_ontology
GRANT INSERT ON argos.applicability_runs TO svc_ontology;
GRANT INSERT, SELECT ON argos.inventory_snapshot_shapes_data, argos.ontology_bundles TO svc_ontology;
GRANT INSERT, SELECT, UPDATE ON argos.load_budget TO svc_ontology;
GRANT INSERT, UPDATE ON argos.connector_queries TO svc_ontology;
GRANT SELECT ON argos.audit_journal, argos.ontology_quads, argos.systems TO svc_ontology;

-- svc_webhook
GRANT INSERT, SELECT ON argos.webhooks TO svc_webhook;
GRANT INSERT, SELECT, UPDATE ON argos.webhook_deliveries TO svc_webhook;
GRANT SELECT ON argos.audit_journal TO svc_webhook;

-- The inventory graph (Apache AGE). AGE is preloaded (shared_preload_libraries), so no service
-- needs LOAD, which only a superuser may run.
GRANT USAGE ON SCHEMA ag_catalog, inventory TO svc_ai_gateway, svc_api, svc_challenge, svc_inventory, svc_ontology;
GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog TO svc_ai_gateway, svc_api, svc_challenge, svc_inventory, svc_ontology;
GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO svc_ai_gateway, svc_api, svc_challenge, svc_inventory, svc_ontology;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA inventory TO svc_api, svc_inventory;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA inventory TO svc_api, svc_inventory;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory
  GRANT SELECT ON TABLES TO svc_ai_gateway, svc_api, svc_challenge, svc_inventory, svc_ontology;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory
  GRANT INSERT, UPDATE, DELETE ON TABLES TO svc_api, svc_inventory;

-- argos_ai (F06-01) was the gateway's role with SELECT on every table (security review F09-02,
-- SEC-051). It keeps its name for the barrier tests and inherits the narrow svc_ai_gateway.
REVOKE ALL ON ALL TABLES IN SCHEMA argos FROM argos_ai;
ALTER DEFAULT PRIVILEGES IN SCHEMA argos REVOKE SELECT ON TABLES FROM argos_ai;
GRANT svc_ai_gateway TO argos_ai;
