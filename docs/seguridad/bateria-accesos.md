# Batería de accesos indebidos

**Generado:** 2026-09-24 10:39 UTC · **Commit:** `a2436af` · **API atacada:** http://127.0.0.1:8000 · **Confidencialidad:** `client`

Informe generado por `tests/security/test_access_battery.py` y `tools/security_report.py` (F09-15). La batería ataca el contenedor `api` desplegado con tokens reales del realm, como lo haría alguien dentro de la red, y comprueba después el estado: una denegación que dejó efecto no es una denegación. No se edita a mano.

## Resumen

| Categoría | Pruebas | Correctas | Fallidas |
|---|---|---|---|
| matrix | 78 | 78 | 0 |
| second factor | 2 | 2 | 0 |
| tokens | 33 | 33 | 0 |
| separation of duties | 4 | 4 | 0 |
| surface | 8 | 8 | 0 |
| internal services | 3 | 3 | 0 |
| public services | 5 | 5 | 0 |
| security log | 3 | 3 | 0 |

## Fallos

Ningún fallo: cada intento indebido fue rechazado y no dejó efecto.

## Combinaciones probadas

### Matriz rol × permiso con tokens reales

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| campaign_manager POST /api/v1/inventory/review-queue/{node_key} | 403 | 403 | correcto |
| campaign_manager POST /api/v1/campaigns/{campaign_id}/gates/{gate}/approve | 403 | 403 | correcto |
| campaign_manager POST /api/v1/campaigns/{campaign_id}/synthetic/authorize | 403 | 403 | correcto |
| campaign_manager POST /api/v1/findings/{finding_id}/transition | 403 | 403 | correcto |
| campaign_manager GET /api/v1/credentials/preview | 403 | 403 | correcto |
| campaign_manager POST /api/v1/credentials | 403 | 403 | correcto |
| campaign_manager POST /api/v1/credentials/{credential_id}/revoke | 403 | 403 | correcto |
| campaign_manager POST /api/v1/webhooks | 403 | 403 | correcto |
| campaign_manager GET /api/v1/webhooks | 403 | 403 | correcto |
| campaign_manager GET /api/v1/webhooks/{webhook_id}/deliveries | 403 | 403 | correcto |
| campaign_manager GET /api/v1/security/events | 403 | 403 | correcto |
| campaign_manager POST /api/v1/system/updates | 403 | 403 | correcto |
| campaign_manager POST /api/v1/support/diagnostics | 403 | 403 | correcto |
| campaign_manager GET /api/v1/support/diagnostics/{diagnostics_id} | 403 | 403 | correcto |
| campaign_manager POST /api/v1/support/diagnostics/{diagnostics_id}/package | 403 | 403 | correcto |
| campaign_manager POST /api/v1/airgap/imports | 403 | 403 | correcto |
| campaign_manager POST /api/v1/airgap/exports | 403 | 403 | correcto |
| campaign_manager: journal entries left by 17 refusals | 0 | 0 | correcto |
| dpo_reviewer POST /api/v1/campaigns | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/campaigns/{campaign_id}/launch | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/campaigns/{campaign_id}/remediation | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/findings/{finding_id}/verify | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/credentials/{credential_id}/revoke | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/webhooks | 403 | 403 | correcto |
| dpo_reviewer GET /api/v1/webhooks | 403 | 403 | correcto |
| dpo_reviewer GET /api/v1/webhooks/{webhook_id}/deliveries | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/synthetic/{injection_id}/confirm-injection | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/synthetic/{injection_id}/confirm-exercise | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/synthetic/{injection_id}/confirm-revert | 403 | 403 | correcto |
| dpo_reviewer GET /api/v1/security/events | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/system/updates | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/support/diagnostics | 403 | 403 | correcto |
| dpo_reviewer GET /api/v1/support/diagnostics/{diagnostics_id} | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/support/diagnostics/{diagnostics_id}/package | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/airgap/imports | 403 | 403 | correcto |
| dpo_reviewer POST /api/v1/airgap/exports | 403 | 403 | correcto |
| dpo_reviewer: journal entries left by 18 refusals | 0 | 0 | correcto |
| platform_admin POST /api/v1/inventory/review-queue/{node_key} | 403 | 403 | correcto |
| platform_admin POST /api/v1/campaigns | 403 | 403 | correcto |
| platform_admin POST /api/v1/campaigns/{campaign_id}/launch | 403 | 403 | correcto |
| platform_admin POST /api/v1/campaigns/{campaign_id}/gates/{gate}/approve | 403 | 403 | correcto |
| platform_admin POST /api/v1/campaigns/{campaign_id}/synthetic/authorize | 403 | 403 | correcto |
| platform_admin POST /api/v1/campaigns/{campaign_id}/remediation | 403 | 403 | correcto |
| platform_admin POST /api/v1/findings/{finding_id}/transition | 403 | 403 | correcto |
| platform_admin POST /api/v1/findings/{finding_id}/verify | 403 | 403 | correcto |
| platform_admin GET /api/v1/credentials/preview | 403 | 403 | correcto |
| platform_admin POST /api/v1/credentials | 403 | 403 | correcto |
| platform_admin GET /api/v1/approvals | 403 | 403 | correcto |
| platform_admin POST /api/v1/synthetic/{injection_id}/confirm-injection | 403 | 403 | correcto |
| platform_admin POST /api/v1/synthetic/{injection_id}/confirm-exercise | 403 | 403 | correcto |
| platform_admin POST /api/v1/synthetic/{injection_id}/confirm-revert | 403 | 403 | correcto |
| platform_admin: journal entries left by 14 refusals | 0 | 0 | correcto |
| read_only_auditor POST /api/v1/inventory/review-queue/{node_key} | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/campaigns | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/campaigns/{campaign_id}/launch | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/campaigns/{campaign_id}/gates/{gate}/approve | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/campaigns/{campaign_id}/synthetic/authorize | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/campaigns/{campaign_id}/remediation | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/findings/{finding_id}/transition | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/findings/{finding_id}/verify | 403 | 403 | correcto |
| read_only_auditor GET /api/v1/credentials/preview | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/credentials | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/credentials/{credential_id}/revoke | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/assistant/ask | 403 | 403 | correcto |
| read_only_auditor GET /api/v1/approvals | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/webhooks | 403 | 403 | correcto |
| read_only_auditor GET /api/v1/webhooks | 403 | 403 | correcto |
| read_only_auditor GET /api/v1/webhooks/{webhook_id}/deliveries | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/synthetic/{injection_id}/confirm-injection | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/synthetic/{injection_id}/confirm-exercise | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/synthetic/{injection_id}/confirm-revert | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/system/updates | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/support/diagnostics | 403 | 403 | correcto |
| read_only_auditor GET /api/v1/support/diagnostics/{diagnostics_id} | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/support/diagnostics/{diagnostics_id}/package | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/airgap/imports | 403 | 403 | correcto |
| read_only_auditor POST /api/v1/airgap/exports | 403 | 403 | correcto |
| read_only_auditor: journal entries left by 25 refusals | 0 | 0 | correcto |

### Segundo factor

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| platform_admin signs in without the TOTP code | 401 | 401 | correcto |
| dpo_reviewer signs in without the TOTP code | 401 | 401 | correcto |

### Tokens indebidos

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| signed with another key (same kid) | 401 | 401 | correcto |
| alg none | 401 | 401 | correcto |
| real signature over a changed payload (roles added) | 401 | 401 | correcto |
| expired (client argos-expiring, 5 s) | 401 | 401 | correcto |
| audience of another client (argos-other) | 401 | 401 | correcto |
| issuer of another realm (master, admin-cli) | 401 | 401 | correcto |
| account without roles GET /api/v1/systems | 403 | 403 | correcto |
| account without roles GET /api/v1/inventory/coverage | 403 | 403 | correcto |
| account without roles GET /api/v1/inventory/nodes/{node_key} | 403 | 403 | correcto |
| account without roles GET /api/v1/inventory/review-queue | 403 | 403 | correcto |
| account without roles POST /api/v1/inventory/review-queue/{node_key} | 403 | 403 | correcto |
| account without roles POST /api/v1/campaigns | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns/{campaign_id} | 403 | 403 | correcto |
| account without roles POST /api/v1/campaigns/{campaign_id}/launch | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns/{campaign_id}/plan | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns/{campaign_id}/progress | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns/{campaign_id}/gates | 403 | 403 | correcto |
| account without roles POST /api/v1/campaigns/{campaign_id}/gates/{gate}/approve | 403 | 403 | correcto |
| account without roles GET /api/v1/campaigns/{campaign_id}/verdicts | 403 | 403 | correcto |
| account without roles POST /api/v1/campaigns/{campaign_id}/synthetic/authorize | 403 | 403 | correcto |
| account without roles POST /api/v1/campaigns/{campaign_id}/remediation | 403 | 403 | correcto |
| account without roles GET /api/v1/findings | 403 | 403 | correcto |
| account without roles GET /api/v1/findings/{finding_id} | 403 | 403 | correcto |
| account without roles POST /api/v1/findings/{finding_id}/transition | 403 | 403 | correcto |
| account without roles POST /api/v1/findings/{finding_id}/verify | 403 | 403 | correcto |
| account without roles GET /api/v1/evidence/{campaign_id}/chain | 403 | 403 | correcto |
| account without roles GET /api/v1/evidence/{campaign_id}/artifacts | 403 | 403 | correcto |
| account without roles GET /api/v1/evidence/{campaign_id}/journal/{seq} | 403 | 403 | correcto |
| account without roles GET /api/v1/evidence/artifacts/{verdict_id} | 403 | 403 | correcto |
| account without roles GET /api/v1/evidence/{campaign_id}/dossier.json | 403 | 403 | correcto |
| no token | 401 with WWW-Authenticate | 401 | correcto |
| access token of a session closed from the console | 401 | 401 | correcto |

### Separación de deberes

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| the campaign manager approves the sampling gate | 403 | 403 | correcto |
| the same DPO approves the sampling gate twice | 409 | 409 | correcto |
| the DPO moves a finding to closed_compliant by hand | 409/422 | 409 | correcto |
| the DPO moves a finding to reopened by hand | 409/422 | 409 | correcto |

### Superficie de la API y la consola

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| undeclared route | 404 problem+json without a stack | 404 | correcto |
| console header: CSP without unsafe-inline | present | present | correcto |
| console header: frame-ancestors 'none' | present | present | correcto |
| console header: X-Content-Type-Options nosniff | present | present | correcto |
| console header: Referrer-Policy | present | present | correcto |
| refresh cookie: path /api/v1/auth, HttpOnly, Secure, SameSite=Strict | yes | yes | correcto |
| POST with Origin https://attacker.example | 403, nothing created | 403 | correcto |
| POST with the Origin of the console | 201 | 201 | correcto |

### Servicios internos

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| ai-gateway without a client certificate | refused | closed | correcto |
| nats without a client certificate | refused | refused (SSLError) | correcto |
| PostgreSQL without TLS | refused | refused | correcto |

### Servicios públicos

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| public verifier /docs | 404 | 404 | correcto |
| public verifier /openapi.json | 404 | 404 | correcto |
| evidence-api /docs | 404 | 404 | correcto |
| evidence-api /openapi.json | 404 | 404 | correcto |
| evidence-api /admin | 404 | 404 | correcto |

### Registro de seguridad

| Caso | Esperado | Obtenido | Resultado |
|---|---|---|---|
| refused attempts of kind auth.token_rejected | recorded | recorded | correcto |
| refused attempts of kind authz.denied | recorded | recorded | correcto |
| refused attempts of kind auth.session_closed | recorded | recorded | correcto |
