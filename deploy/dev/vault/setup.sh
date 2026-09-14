#!/bin/sh
# ARG-009 · configuración idempotente de Vault de desarrollo (modo dev: se pierde al reiniciar el contenedor)
set -eu

montado() { vault secrets list -format=json | grep -q "\"$1/\""; }

montado argos || vault secrets enable -path=argos kv-v2

if ! montado pki; then
  vault secrets enable pki
  vault secrets tune -max-lease-ttl=87600h pki
fi
if ! vault list pki/issuers >/dev/null 2>&1; then
  vault write -field=certificate pki/root/generate/internal \
    common_name="ARGOS Appliance Root CA (desarrollo)" ttl=87600h >/dev/null
fi

if ! montado pki_int; then
  vault secrets enable -path=pki_int pki
  vault secrets tune -max-lease-ttl=8760h pki_int
fi
if ! vault list pki_int/issuers >/dev/null 2>&1; then
  CSR=$(vault write -field=csr pki_int/intermediate/generate/internal common_name="ARGOS Services CA (desarrollo)")
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

# Política EXCLUSIVA de credenciales de conectores (P-04)
printf 'path "argos/data/connectors/*" { capabilities = ["read"] }\n' | vault policy write svc-connector-sdk - >/dev/null

echo "vault de desarrollo configurado"
