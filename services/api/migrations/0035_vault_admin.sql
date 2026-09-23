-- ARG-085 · the administrator Vault's `database` engine uses to create ephemeral users (F09-05).
--
-- Vault connects as `vault_admin`, not as the superuser of the container. The role can create
-- roles and make them members of the service roles (ADMIN OPTION), and nothing else: it cannot
-- create databases, bypass row security or replicate. After the first connection Vault rotates its
-- password (`db/rotate-root`), so only Vault knows it.
--
-- The ephemeral users Vault creates own nothing: revoking them reassigns whatever they could have
-- created to their service role and drops them. Reassigning needs the privileges of both roles, so
-- the roles `vault_admin` creates are granted back to it with SET and INHERIT.
--
-- Roles belong to the cluster: the role exists once, the grants are idempotent.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vault_admin') THEN
    CREATE ROLE vault_admin NOLOGIN CREATEROLE;
  END IF;
END $$;

GRANT svc_api, svc_webhook, svc_challenge, svc_evidence, svc_ai_gateway, svc_example,
      svc_inventory, svc_ontology
   TO vault_admin WITH ADMIN OPTION;

ALTER ROLE vault_admin SET createrole_self_grant = 'set, inherit';
