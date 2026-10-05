#!/bin/sh
# K-04 · idempotent setup of the Vault of the bench. It runs inside the pod vault-0, fed by
# `vault.sh configure`, which puts the root token of the person first on its standard input; running
# it again changes nothing that is in place. The same engines, keys and policies as the development
# Vault (deploy/dev/vault/setup.sh), plus the kubernetes auth method: each service of the bench
# signs in with its own service account (ADR-0014, point 3) and nobody hands it a token.
set -eu

mounted() { vault secrets list -format=json | grep -q "\"$1/\""; }
enabled() { vault auth list -format=json | grep -q "\"$1/\""; }

mounted argos || vault secrets enable -path=argos kv-v2

# The PKI of the bench: a root that only signs the intermediate, and the intermediate that issues
# the certificate of each service (cert-manager, K-06).
if ! mounted pki; then
  vault secrets enable pki
  vault secrets tune -max-lease-ttl=87600h pki
fi
if ! vault list pki/issuers >/dev/null 2>&1; then
  vault write -field=certificate pki/root/generate/internal \
    common_name="ARGOS bench Root CA (not for production)" ttl=87600h >/dev/null
fi
if ! mounted pki_int; then
  vault secrets enable -path=pki_int pki
  vault secrets tune -max-lease-ttl=8760h pki_int
fi
if ! vault list pki_int/issuers >/dev/null 2>&1; then
  CSR=$(vault write -field=csr pki_int/intermediate/generate/internal common_name="ARGOS bench Services CA")
  CERT=$(vault write -field=certificate pki/root/sign-intermediate csr="$CSR" format=pem_bundle ttl=8760h)
  vault write pki_int/intermediate/set-signed certificate="$CERT" >/dev/null
fi
# One certificate per service, 30 days, the names of the services of the cluster.
vault write pki_int/roles/argos-svc \
  allowed_domains="argos-core.svc,argos-services.svc,argos-ai.svc,argos-connect.svc,svc.cluster.local" \
  allow_subdomains=true allow_bare_domains=false allow_localhost=true allow_ip_sans=true \
  key_type=ec key_bits=256 max_ttl=720h ttl=720h >/dev/null
printf 'path "pki_int/issue/argos-svc" { capabilities = ["update"] }\npath "pki_int/sign/argos-svc" { capabilities = ["update"] }\n' \
  | vault policy write argos-cert-issuer - >/dev/null

for svc in inventory ontology challenge evidence credentials api; do
  printf 'path "argos/data/services/%s/*" { capabilities = ["read"] }\n' "$svc" \
    | vault policy write "svc-$svc" - >/dev/null
done
# Exclusive policy for connector credentials (P-04).
printf 'path "argos/data/connectors/*" { capabilities = ["read"] }\n' | vault policy write svc-connector-sdk - >/dev/null

# Signing keys: Ed25519 and never exportable. Releases (ARG-010), content bundles (ARG-040) and
# campaign roots (ARG-064, a TPM key on the appliance).
mounted transit || vault secrets enable transit
for key in argos-release argos-content argos-evidence; do
  vault read "transit/keys/$key" >/dev/null 2>&1 || vault write -f "transit/keys/$key" type=ed25519 >/dev/null
done

# The kubernetes auth method: Vault checks each service account token with the API of the
# cluster (its own account may review tokens, rbac.yaml). The roles that bind an account to its
# policies arrive with each component.
enabled kubernetes || vault auth enable kubernetes
vault write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc" >/dev/null

# K-04 · the bootstrap Job (argos-core/argos-bootstrap) sets up the database engine and nothing
# else: mount it, configure its connection, rotate the password of vault_admin and write the role of
# each service. Its token lives 15 minutes.
printf '%s\n' \
  'path "sys/mounts" { capabilities = ["read"] }' \
  'path "sys/mounts/db" { capabilities = ["create", "read", "update"] }' \
  'path "db/config/argos" { capabilities = ["create", "read", "update"] }' \
  'path "db/rotate-root/argos" { capabilities = ["update"] }' \
  'path "db/roles/svc-*" { capabilities = ["create", "read", "update"] }' \
  | vault policy write argos-bootstrap - >/dev/null
vault write auth/kubernetes/role/bootstrap bound_service_account_names=argos-bootstrap bound_service_account_namespaces=argos-core \
  policies=argos-bootstrap ttl=15m >/dev/null

# K-04 · cert-manager signs the certificate of each service with the intermediate CA, and nothing else.
vault write auth/kubernetes/role/cert-manager bound_service_account_names=cert-manager bound_service_account_namespaces=cert-manager   policies=argos-cert-issuer ttl=15m >/dev/null

echo "bench vault configured"
