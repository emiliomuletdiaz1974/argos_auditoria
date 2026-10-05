-- The connector SDK closes its entry of the prior query journal (ARG-012) with
-- `UPDATE argos.connector_queries ... WHERE journal_seq = ... AND system_id = ... AND finished_at IS NULL`.
-- PostgreSQL asks for SELECT on the columns a WHERE reads, and since 0033 the roles that probe had
-- only INSERT and UPDATE: every probe run under a service role ended in "permission denied for table
-- connector_queries". In development nobody saw it because the probes ran as the owner; the bench,
-- with each service on its own role (K-07), did. Only those three columns, nothing of the statement.
GRANT SELECT (journal_seq, system_id, finished_at) ON argos.connector_queries
  TO svc_api, svc_challenge, svc_evidence, svc_inventory, svc_ontology;
