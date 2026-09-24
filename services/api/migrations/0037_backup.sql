-- ARG-089 · the backup role and the dated results of the restore tests (F09-12).
--
-- `svc_backup` reads everything and writes nothing of the product: `pg_read_all_data` is what
-- `pg_dump` needs, and the role gets no write privilege on any table but its own results. Vault
-- creates its ephemeral login users (`db/roles/svc-backup`, F09-05) as for any other service.
--
-- `argos.restore_tests` keeps one row per restore test, written once: when it was tried, which
-- copy, what was verified and the result. The API reads it for the metric the alerts of
-- Prometheus use (a test older than 35 days, a failed test).
--
-- Roles belong to the cluster: the role exists once, the grants are idempotent.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_backup') THEN
    CREATE ROLE svc_backup NOLOGIN;
  END IF;
END $$;

GRANT pg_read_all_data TO svc_backup;
GRANT svc_backup TO vault_admin WITH ADMIN OPTION;

CREATE TABLE argos.restore_tests (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tested_at         timestamptz NOT NULL,
  snapshot_id       text,
  snapshot_time     timestamptz,
  result            text NOT NULL CHECK (result IN ('passed', 'failed')),
  reasons           jsonb NOT NULL DEFAULT '[]',
  journal_entries   bigint NOT NULL DEFAULT 0,
  journal_intact    boolean,
  security_events   bigint NOT NULL DEFAULT 0,
  security_intact   boolean,
  counts            jsonb NOT NULL DEFAULT '{}',
  evidence_checked  integer NOT NULL DEFAULT 0,
  evidence_ok       boolean,
  duration_seconds  numeric NOT NULL CHECK (duration_seconds >= 0),
  -- A test that passed verified the whole chain of the journal and of the security log.
  CHECK (result = 'failed' OR (journal_intact AND security_intact))
);
CREATE INDEX ix_restore_tests_tested_at ON argos.restore_tests (tested_at DESC);

CREATE TRIGGER restore_tests_write_once
  BEFORE UPDATE OR DELETE ON argos.restore_tests
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_write_once();
CREATE TRIGGER restore_tests_no_truncate
  BEFORE TRUNCATE ON argos.restore_tests
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();

REVOKE ALL ON argos.restore_tests FROM PUBLIC;
GRANT USAGE ON SCHEMA argos TO svc_backup;
GRANT INSERT ON argos.restore_tests TO svc_backup;
GRANT SELECT ON argos.restore_tests TO svc_api;

-- The backup records its runs and its restore tests as itself, and only those.
GRANT EXECUTE ON FUNCTION argos.journal_append(text, text, text) TO svc_backup;
INSERT INTO argos.journal_grants (role_name, actor_pattern, action_pattern, reason) VALUES
  ('svc_backup', 'system:backup', 'backup.%', 'the backups and their restore tests');
GRANT svc_security_writer TO svc_backup;
