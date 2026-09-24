#!/bin/sh
# ARG-009 · idempotent setup of the development Vault (dev mode: state is lost when the container restarts)
set -eu

mounted() { vault secrets list -format=json | grep -q "\"$1/\""; }

mounted argos || vault secrets enable -path=argos kv-v2

if ! mounted pki; then
  vault secrets enable pki
  vault secrets tune -max-lease-ttl=87600h pki
fi
if ! vault list pki/issuers >/dev/null 2>&1; then
  vault write -field=certificate pki/root/generate/internal \
    common_name="ARGOS Appliance Root CA (development)" ttl=87600h >/dev/null
fi

if ! mounted pki_int; then
  vault secrets enable -path=pki_int pki
  vault secrets tune -max-lease-ttl=8760h pki_int
fi
if ! vault list pki_int/issuers >/dev/null 2>&1; then
  CSR=$(vault write -field=csr pki_int/intermediate/generate/internal common_name="ARGOS Services CA (development)")
  CERT=$(vault write -field=certificate pki/root/sign-intermediate csr="$CSR" format=pem_bundle ttl=8760h)
  vault write pki_int/intermediate/set-signed certificate="$CERT" >/dev/null
fi
# ARG-083 · one certificate per service, 30 days, renewed at 20 by cert-issuer (F09-06). The bare
# names are the services of the development compose; the domains with subdomains, those of k3s.
vault write pki_int/roles/argos-svc \
  allowed_domains="argos-core,argos-services,argos-edge,argos-ai,api,webhook,challenge,evidence,ai-gateway,example,postgres,nats,vault,argos-dev,localhost" \
  allow_subdomains=true allow_bare_domains=true allow_localhost=true allow_ip_sans=true \
  key_type=ec key_bits=256 max_ttl=720h ttl=720h >/dev/null
printf 'path "pki_int/issue/argos-svc" { capabilities = ["update"] }\n' | vault policy write argos-cert-issuer - >/dev/null

for svc in inventory ontology challenge evidence credentials api; do
  printf 'path "argos/data/services/%s/*" { capabilities = ["read"] }\npath "pki_int/issue/argos-svc" { capabilities = ["update"] }\n' "$svc" \
    | vault policy write "svc-$svc" - >/dev/null
done

# EXCLUSIVE policy for connector credentials (P-04)
printf 'path "argos/data/connectors/*" { capabilities = ["read"] }\n' | vault policy write svc-connector-sdk - >/dev/null

# ARG-010 · release signing key: Ed25519, not exportable
mounted transit || vault secrets enable transit
vault read transit/keys/argos-release >/dev/null 2>&1 || vault write -f transit/keys/argos-release type=ed25519 >/dev/null
# ARG-040 · ontology content signing key: Ed25519, not exportable, separate from releases
vault read transit/keys/argos-content >/dev/null 2>&1 || vault write -f transit/keys/argos-content type=ed25519 >/dev/null
# ARG-064 · campaign root signing key: Ed25519, not exportable, one per appliance (a TPM key in production)
vault read transit/keys/argos-evidence >/dev/null 2>&1 || vault write -f transit/keys/argos-evidence type=ed25519 >/dev/null

# ARG-089 · the password of the restic repository (F09-12). A fixed development value: the dev
# Vault loses its state on restart, and a new password would leave the copies unreadable. On the
# appliance it is generated once and kept in the raft storage of Vault (and in the sealed
# recovery kit of the client).
vault kv get argos/platform/backup >/dev/null 2>&1 \
  || vault kv put argos/platform/backup restic_password=dev-only-restic-backup >/dev/null
printf 'path "argos/data/platform/backup" { capabilities = ["read"] }\npath "db/creds/svc-backup" { capabilities = ["read"] }\npath "sys/leases/revoke" { capabilities = ["update"] }\n' \
  | vault policy write svc-backup - >/dev/null

echo "development vault configured"
