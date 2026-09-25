-- ARG-092 · what the dashboards of compliance and of the AI platform show (F10-04).
--
-- The health service publishes, as aggregates only, the open findings by severity, the time to a
-- verified remediation, the coverage of the inventory, and the use, latency, quota and calibration
-- of the AI gateway. It reads those tables and still writes nothing but its own facts: no prompt,
-- no hash of a prompt and no finding detail leaves the queries, which count and aggregate.
GRANT SELECT ON argos.findings, argos.catalog_coverage, argos.ai_usage, argos.ai_quotas
   TO svc_health;
