#!/bin/sh
# ARG-085 · Vault's `database` engine: one ephemeral PostgreSQL user per service (F09-05).
#
# Each role `svc-<service>` creates a user that is a member of `svc_<service>` (migration 0033),
# valid until its lease ends (24 h, never more than 72 h), and drops it when the lease is revoked:
# a credential stolen today is no good tomorrow. Vault connects as `vault_admin` (migration 0035),
# never as the superuser, and rotates its password right away so only Vault knows it.
#
# POSIX sh: it runs inside the Vault container of development (`sh -s`) and on the appliance.
# Needs VAULT_ADDR, VAULT_TOKEN and VAULT_DB_ADMIN_PW; the password never goes on a command line.
set -eu

: "${VAULT_DB_ADMIN_PW:?the password of vault_admin, in the environment}"
DB_HOST="${ARGOS_DB_HOST:-postgres:5432}"
DB_NAME="${ARGOS_DB_NAME:-argos}"
# F09-06: Vault verifies PostgreSQL with the internal CA, as every other client does.
DB_TLS="${ARGOS_DB_TLS:-sslmode=verify-full&sslrootcert=/run/tls/ca.crt}"
DEFAULT_TTL="${ARGOS_DB_DEFAULT_TTL:-24h}"
MAX_TTL="${ARGOS_DB_MAX_TTL:-72h}"

vault secrets list -format=json | grep -q '"db/"' || vault secrets enable -path=db database

# The password travels in a JSON body read from standard input, not as an argument.
printf '{"plugin_name":"postgresql-database-plugin","allowed_roles":"svc-*","connection_url":"postgresql://{{username}}:{{password}}@%s/%s?%s","username":"vault_admin","password":"%s","password_authentication":"scram-sha-256"}' \
  "$DB_HOST" "$DB_NAME" "$DB_TLS" "$VAULT_DB_ADMIN_PW" | vault write "db/config/$DB_NAME" -
vault write -f "db/rotate-root/$DB_NAME" >/dev/null

# Vault role -> PostgreSQL role of the service.
for pair in api:svc_api webhook:svc_webhook challenge:svc_challenge evidence:svc_evidence \
            ai-gateway:svc_ai_gateway example:svc_example inventory:svc_inventory \
            ontology:svc_ontology; do
  name="${pair%%:*}"
  role="${pair#*:}"
  vault write "db/roles/svc-$name" \
    db_name="$DB_NAME" \
    default_ttl="$DEFAULT_TTL" max_ttl="$MAX_TTL" \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' IN ROLE $role;" \
    revocation_statements="REASSIGN OWNED BY \"{{name}}\" TO $role; DROP ROLE IF EXISTS \"{{name}}\";" \
    >/dev/null
done
echo "dynamic database credentials ready: ttl $DEFAULT_TTL, at most $MAX_TTL"
