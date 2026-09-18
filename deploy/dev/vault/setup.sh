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
vault write pki_int/roles/argos-svc \
  allowed_domains="argos-core,argos-services,argos-edge,argos-ai" \
  allow_subdomains=true max_ttl=720h ttl=720h >/dev/null

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

echo "development vault configured"
