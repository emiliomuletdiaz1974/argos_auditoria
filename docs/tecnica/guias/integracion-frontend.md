---
id: GUIA-integracion-frontend
kind: guide
title: Guía de integración del front end con la API v1
phases: ["08"]
version: 0.3.0
commit: pendiente
date: 2026-10-05
status: current
confidentiality: client
---

# Guía de integración del front end con la API v1

Esta guía es para el equipo que construye el front end de ARGOS. Explica qué endpoints hay, para qué sirve cada uno, qué rol lo puede usar y en qué orden se encadenan en los flujos de trabajo reales.

El contrato exacto (esquemas, tipos y códigos de cada operación) es `services/api/openapi.json`. Esta guía no lo sustituye: si discrepan, manda el contrato. En desarrollo también se sirve en `GET /api/v1/openapi.json`, con la vista interactiva en `/api/v1/docs`.

> **Front en otro dominio:** la API lo admite desde C-03 si su origen está en `ARGOS_FRONTEND_ORIGINS`. Las llamadas de sesión llevan la cabecera `X-Argos-Session: 1` (ver [§3](#3-front-end-en-otro-origen)).

## 1. Lo que hay que saber antes de empezar

- **La API no sirve páginas.** Desde el 2026-09-29 la API no construye ni sirve la consola de la Fase 08 (nota de desviación ARG-073). Todo lo que no es una ruta de la API responde `404` en `application/problem+json`. El front end es una aplicación aparte, con su propio despliegue.
- **Todo cuelga de `/api/v1`.** La única ruta fuera es `GET /health`.
- **No hay rutas privadas para el front.** Lo que hace el front lo puede hacer cualquier integración con el mismo token y la misma matriz de permisos.
- **El servidor decide, el front enseña.** Las transiciones permitidas de un hallazgo, las compuertas pendientes o si algo se puede verificar vienen en las respuestas. El front no debe recalcularlas ni ofrecer acciones que la respuesta no trae.
- **Los identificadores son UUID** (`campaign_id`, `finding_id`, `verdict_id`…), salvo `node_key` (huella hexadecimal de un nodo del grafo) y `gate` (`start`, `sampling`).
- **Los textos de la interfaz van en castellano** (pliego P-18). Las claves, estados y códigos de la API están en inglés y no se traducen en el contrato: se traducen al pintarlos.

## 2. Autenticación y sesión

### 2.1 Roles

Los roles vienen del realm `argos` de Keycloak, en el token de acceso.

| Rol | Quién es | Resumen |
|---|---|---|
| `platform_admin` | Administración de la plataforma | Sistemas, integraciones, revocaciones, operación, soporte. No aprueba ni juzga. |
| `campaign_manager` | Responsable de campañas | Planifica, lanza y reejecuta campañas; confirma pasos del sujeto sintético. |
| `dpo_reviewer` | DPO | Aprueba compuertas, decide sobre hallazgos y columnas, emite credenciales. |
| `read_only_auditor` | Auditoría | Solo lectura, más el registro de seguridad y la operación. |

`campaign_manager` y `dpo_reviewer` son **incompatibles**: un token que lleve los dos se rechaza en todas las rutas. El motor también rechaza que quien creó una campaña la apruebe.

### 2.2 Inicio de sesión (OIDC con PKCE)

El front no guarda ningún secreto de cliente. El flujo es:

1. El front genera un `code_verifier` (43–128 caracteres `[A-Za-z0-9-._~]`) y su reto S256, y guarda el verificador y un `state` en `sessionStorage` solo durante la redirección.
2. Redirige a Keycloak: `GET {issuer}/protocol/openid-connect/auth` con `client_id`, `redirect_uri`, `response_type=code`, `scope=openid`, `code_challenge`, `code_challenge_method=S256` y `state`.
3. A la vuelta, comprueba el `state` y llama a la API:

   ```http
   POST /api/v1/auth/session
   Content-Type: application/json
   X-Argos-Session: 1

   {"code": "...", "code_verifier": "...", "redirect_uri": "https://front.example/callback"}
   ```

4. La API cambia el código en Keycloak y responde `{"access_token", "token_type": "Bearer", "expires_in"}`. El **token de refresco no llega al JavaScript**: viaja en la cookie `argos_refresh` (`HttpOnly`, `Secure`, `SameSite=None` con el front en otro dominio, `Path=/api/v1/auth`).
5. El front borra el verificador y el `state`, y guarda el token de acceso **solo en memoria** (nunca en `localStorage` ni en `sessionStorage`).

El cliente público que usa la API es `argos-console` (`services/api/argos_api/keycloak.py`). Tiene que admitir el `redirect_uri` y el origen del front (ver §3).

### 2.3 Llamadas autenticadas y renovación

- Cada llamada lleva `Authorization: Bearer <access_token>`.
- Un `401` sin más: se llama **una vez** a `POST /api/v1/auth/refresh` (sin cuerpo, con la cookie y `X-Argos-Session: 1`) y se reintenta **una vez**. Si el refresco da `401`, la sesión ha terminado o el navegador no envió la cookie: se vuelve a Keycloak (§3). No hay que entrar en bucle.
- Un `401` con `WWW-Authenticate: Bearer error="insufficient_user_authentication"` no es una sesión caducada: la acción pide **segundo factor** (§2.4).
- `POST /api/v1/auth/logout` (con `X-Argos-Session: 1`) revoca el refresco en Keycloak, borra la cookie y cierra la sesión también para los tokens de acceso que siguieran vivos. Responde `204`.

### 2.4 Segundo factor (step-up)

Las acciones que deciden piden un token emitido con TOTP (`amr` contiene `otp`). Sin él, la API responde `401` con `error="insufficient_user_authentication"` y `acr_values="otp"` (RFC 9470). El front debe explicar a la persona que la acción pide su código y volver a iniciar sesión pidiendo ese nivel.

Permisos con segundo factor: `campaigns.approve`, `findings.transition`, `credentials.create`, `credentials.revoke`, `synthetic.authorize`, `inventory.review`, `webhooks.create`, `system.update`, `support.package`, `airgap.import`, `airgap.export`, `systems.create`. Solo `platform_admin` y `dpo_reviewer` tienen TOTP.

## 3. Front end en otro origen

Front y API viven en dominios distintos (decisión C-02, 2026-09-29). Desde C-03 la API lo admite así:

| Qué | Cómo funciona |
|---|---|
| Orígenes permitidos | `ARGOS_FRONTEND_ORIGINS` en la API: la lista exacta de orígenes del front (`https://front.example`, sin ruta ni barra final), separados por comas. Solo `https`; `http` solo para `localhost` o `127.0.0.1` fuera de producción. La API no arranca si un origen no es exacto (`*`, `null`, con ruta…). |
| Comprobación de `Origin` | Un `POST` con `Origin` pasa si es el host de la API o uno de la lista, comparado entero. Cualquier otro recibe `403` ("a change sent from another origin"). |
| CORS | Solo para los orígenes de la lista, con credenciales. Métodos `GET` y `POST`. Cabeceras admitidas: `Authorization`, `Content-Type`, `Idempotency-Key` y `X-Argos-Session`. Cabeceras legibles por el front: `WWW-Authenticate` (el segundo factor, §2.4) y `Content-Disposition` (el nombre de las descargas). La petición previa se guarda 10 minutos. |
| Cookie de refresco | Con orígenes en la lista, `argos_refresh` es `SameSite=None; Secure; HttpOnly; Path=/api/v1/auth`. Sin lista, sigue `SameSite=Strict`. |
| Anti-CSRF de la sesión | `POST /auth/session`, `/auth/refresh` y `/auth/logout` exigen la cabecera `X-Argos-Session: 1`. Sin ella responden `403`. Ninguna página puede enviarla sin una petición previa CORS, y la API solo se la concede a los orígenes de la lista. |

**Lo que tiene que hacer el front:**

- Las llamadas a `/api/v1/auth/*` llevan `credentials: "include"` y la cabecera `X-Argos-Session: 1`. El resto de llamadas van con `Authorization: Bearer …` y sin credenciales.
- Su `redirect_uri` y su origen tienen que estar en el cliente `argos-console` del realm (`redirectUris` y `webOrigins`). Eso lo configura quien instala.

**Cuando el navegador bloquea la cookie.** Con dominios distintos, `argos_refresh` es una cookie de terceros. Safari la bloquea por defecto, y otros navegadores pueden hacerlo según su configuración. Entonces `POST /auth/refresh` responde `401` ("no session cookie"). El front no debe tratarlo como un error: redirige a la persona a Keycloak (§2.2, paso 2) y, si su sesión en el realm sigue viva, Keycloak devuelve el código al momento, sin pedir la contraseña. Lo que se pierde es el estado de la pantalla, así que conviene guardar en `sessionStorage` la ruta en la que estaba la persona (nunca el token) para devolverla allí.

**En desarrollo:** `make dev` configura `ARGOS_FRONTEND_ORIGINS=http://127.0.0.1:5173`, que el realm ya admite como vuelta. Un front servido en ese puerto funciona contra `http://127.0.0.1:8000` sin más cambios.

**Contra el banco de pruebas** (datos sintéticos, K-08):

| Qué | Dirección |
|---|---|
| API | `https://api.34-134-21-66.sslip.io/api/v1` |
| Emisor (realm) | `https://id.34-134-21-66.sslip.io/realms/argos` |
| Autorización (PKCE) | `https://id.34-134-21-66.sslip.io/realms/argos/protocol/openid-connect/auth` |
| Origen admitido | `http://localhost:5173` (cliente `argos-console`) |

- El front se sirve en `http://localhost:5173` y vuelve a `http://localhost:5173/...`. Otro puerto u otro nombre (`127.0.0.1`) no se admite: el origen tiene que ser exactamente ese.
- El banco corre en `staging` y no publica `/api/v1/docs` ni `/api/v1/openapi.json`. El contrato está en el repositorio (§8).
- Las cuentas tienen una contraseña temporal que se cambia en el primer acceso. `platform_admin` y `dpo_reviewer` configuran además su TOTP.
- El asistente responde `503`: el banco no tiene modelo de IA.
- **Mientras la VM tenga cerrados los puertos 80 y 443:** se entra por un túnel SSH (`platform/k8s/bench/tunnel.sh`), con los dos nombres apuntando a `127.0.0.1` en el fichero `hosts`. Las direcciones son las mismas, pero el certificado es el propio de Traefik: hay que aceptar el aviso una vez en el navegador, abriendo cada uno de los dos nombres, y desactivar la verificación SSL en Postman.

## 4. Convenciones comunes

### 4.1 Errores

Todos los errores son `application/problem+json` (RFC 9457):

```json
{"type": "about:blank", "title": "conflict", "status": 409,
 "detail": "illegal transition pending_verification -> risk_accepted",
 "instance": "/api/v1/findings/…/transition"}
```

| Código | Significa | Qué hace el front |
|---|---|---|
| `400` | Un valor ilegible (un cursor que no es nuestro, por ejemplo) | Mostrar `detail`; no reintentar igual |
| `401` | Sin token válido, o falta segundo factor | §2.3 y §2.4 |
| `403` en `/auth/*` | Falta `X-Argos-Session: 1` | Enviar la cabecera (§3) |
| `403` | El rol no lo permite | No debería pasar si el front solo ofrece lo que el rol puede hacer |
| `404` | No existe | Mostrar que no existe |
| `409` | El estado no lo permite (transición ilegal, campaña aún no preparada…) | Mostrar `detail` y refrescar el recurso: el estado cambió |
| `422` | Cuerpo inválido | Mostrar `detail`, que dice qué campo y por qué |
| `429` | Cupo agotado (asistente) | Avisar y dejar reintentar más tarde |
| `501` | Ruta declarada sin implementar (`GET /approvals`) | No usarla |
| `503` | Algo no está configurado o no responde (modelo local, base de datos, Temporal) | Mostrar que el servicio no está disponible |

`detail` está en inglés. Sirve para diagnosticar; el front debe traducir los casos que enseña a la persona.

### 4.2 Paginación

Los listados devuelven `{"items": [...], "next": "<cursor>" | null}` y aceptan `?limit=` (por defecto 50, máximo 200) y `?cursor=`. Para la página siguiente se pasa `next` como `cursor`. El cursor es opaco: no se construye ni se interpreta. Un listado se ordena del más reciente al más antiguo, salvo los hallazgos (peor primero).

### 4.3 Idempotencia

Los `POST` que crean aceptan `Idempotency-Key` (1–128 caracteres `[A-Za-z0-9_-]`). Si se repite con la misma petición, la API devuelve el primer resultado; con otra petición distinta, `409`. El front debe generar una clave por intento de acción y reutilizarla si reintenta por un fallo de red.

### 4.4 Diario de auditoría

Toda mutación deja un asiento en el diario con la persona que la hizo. No hace falta nada en el front, pero conviene decírselo a la persona en las acciones que deciden (aceptar un riesgo, emitir una credencial).

## 5. Endpoints por recurso

Leyenda de roles: **A** `platform_admin` · **M** `campaign_manager` · **D** `dpo_reviewer` · **R** `read_only_auditor` · **2FA** pide segundo factor.

### 5.1 Salud y sesión

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /health` | La API está viva | Abierta |
| `POST /api/v1/auth/session` | Abrir sesión con el código PKCE (§2.2) | Abierta, con `X-Argos-Session: 1` |
| `POST /api/v1/auth/refresh` | Nuevo token de acceso desde la cookie | Abierta (cookie), con `X-Argos-Session: 1` |
| `POST /api/v1/auth/logout` | Cerrar sesión | Abierta (cookie), con `X-Argos-Session: 1` |

### 5.2 Sistemas

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/systems` | Sistemas registrados (paginado) | A M D R |
| `POST /api/v1/systems` | Registrar un sistema a auditar: `name`, `kind` (`rdbms`, `files`, `api`, `directory`, `clinical`, `ai`, `other`), `connector`, `config`, `environment`, `owner`. Respeta el límite de la talla del appliance | A · 2FA |

### 5.3 Inventario

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/inventory/coverage` | Cobertura por sistema, frescura de la última exploración, columnas pendientes de revisión y de categoría especial | A M D R |
| `GET /api/v1/inventory/review-queue` | Columnas que esperan decisión humana, con su categoría propuesta y confianza (paginado) | A M D R |
| `POST /api/v1/inventory/review-queue/{node_key}` | Decidir una columna: `decision` = `accept` (con la `category` que se vio), `reject` o `correct` (con la `category` correcta); `note` opcional. `409` si la propuesta cambió mientras se leía | D · 2FA |
| `GET /api/v1/inventory/nodes/{node_key}` | Un nodo del grafo: vecindario (`?limit=`), procedencia y línea temporal de cambios | A M D R |
| `POST /api/v1/inventory/graph` | GraphQL del grafo, para vecindarios de profundidad variable | A M D R |

`node_key` sale de la cola de revisión o de los vecinos de otro nodo.

### 5.4 Campañas

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/campaigns` | Campañas, de la más reciente a la más antigua | A M D R |
| `POST /api/v1/campaigns` | Planificar: `{"name", "scope": {"system_ids": [...]}}`. Nace en `planned` | M |
| `GET /api/v1/campaigns/{id}` | Estado: `planned`, `pinned`, `running`, `sealed` | A M D R |
| `POST /api/v1/campaigns/{id}/launch` | Lanzar. Prepara el plan y se para en la compuerta `start`. `409` si ya estaba lanzada | M |
| `GET /api/v1/campaigns/{id}/plan` | Lo que la campaña va a preguntar, literal, antes de preguntar nada. `409` hasta que la campaña está preparada | A M D R |
| `GET /api/v1/campaigns/{id}/gates` | Compuertas con sus aprobaciones: cuántas hay, de quién y cuántas faltan | A M D R |
| `POST /api/v1/campaigns/{id}/gates/{gate}/approve` | Aprobar `start` o `sampling` (`note` opcional). `sampling` pide dos personas distintas | D · 2FA |
| `GET /api/v1/campaigns/{id}/progress` | Progreso del workflow: `status` (`preparing`, `awaiting:<gate>`, `running`), `done`, `total`, `findings`, sistemas en pausa con su motivo. `409` si no está en marcha | A M D R |
| `GET /api/v1/campaigns/{id}/verdicts` | Veredictos tal como se escribieron (paginado) | A M D R |
| `POST /api/v1/campaigns/{id}/remediation` | Reejecutar lo que encontró la campaña para verificar la subsanación. `202` | M |
| `GET /api/v1/approvals` | **No usar:** responde `501`. Las compuertas pendientes se leen en `/campaigns/{id}/gates` | M D |

### 5.5 Hallazgos

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/findings` | Hallazgos, peor primero. Filtros `status`, `severity`, `campaign_id` | A M D R |
| `GET /api/v1/findings/{id}` | El porqué completo (criterio, valor observado, muestreo, asiento del diario, obligación), `allowed_transitions` e historia | A M D R |
| `POST /api/v1/findings/{id}/transition` | Mover el hallazgo: `{"to", "note", "risk_expiry"}` | D · 2FA |
| `POST /api/v1/findings/{id}/verify` | Reejecutar el reto para verificar la subsanación. Solo con el hallazgo en `pending_verification` | M |

Estados y transiciones que puede pedir una persona:

| Desde | Puede pasar a |
|---|---|
| `open` | `in_remediation`, `risk_accepted` |
| `in_remediation` | `pending_verification`, `risk_accepted` |
| `reopened` | `in_remediation`, `risk_accepted` |
| `pending_verification` | Nada a mano: lo cierra (`closed_compliant`) o lo reabre (`reopened`) la verificación |
| `risk_accepted` | Nada a mano: vuelve a `reopened` cuando caduca la aceptación |
| `closed_compliant` | Nada |

`risk_accepted` exige `note` y una `risk_expiry` futura (`AAAA-MM-DD`). **No hay botón de cerrar**: el front ofrece solo lo que trae `allowed_transitions`.

### 5.6 Evidencia

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/evidence/{campaign_id}/chain` | Estado de cada eslabón: artefactos, raíz, firma, sello y diario anclado | A M D R |
| `GET /api/v1/evidence/{campaign_id}/artifacts` | Índice de artefactos (paginado) | A M D R |
| `GET /api/v1/evidence/artifacts/{verdict_id}` | Artefacto de un veredicto con su prueba de inclusión | A M D R |
| `GET /api/v1/evidence/{campaign_id}/journal/{seq}` | Asiento del diario citado por un veredicto | A M D R |
| `GET /api/v1/evidence/{campaign_id}/dossier.json` | Expediente, JSON canónico | A M D R |
| `GET /api/v1/evidence/{campaign_id}/dossier.pdf` | Expediente, PDF | A M D R |
| `GET /api/v1/evidence/{campaign_id}/bundle` | Paquete para el comprobador público | A M D R |

Las descargas llevan el token en la cabecera: el front las pide con `fetch`, obtiene un `Blob` y lo ofrece para guardar. No se pueden enlazar con un `<a href>` normal. Una firma de desarrollo o un sello en cola se enseñan como tales, nunca como si fueran válidos en producción.

### 5.7 Credenciales verificables

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/credentials/preview?campaign_id=` | Qué afirmaría la credencial, campo a campo, y su `dossier_sha256` | A M D R |
| `POST /api/v1/credentials` | Emitir: `{"campaign_id", "dossier_sha256"}` de la vista previa que se leyó. `409` si el expediente cambió | D · 2FA |
| `GET /api/v1/credentials/{id}` | Credencial y su estado | A M D R |
| `POST /api/v1/credentials/{id}/revoke` | Revocar con `reason` | A · 2FA |

El front debe enseñar la vista previa completa y pedir una confirmación explícita antes de emitir.

### 5.8 Sujeto sintético (ADR-0008)

| Método y ruta | Para qué | Roles |
|---|---|---|
| `POST /api/v1/campaigns/{id}/synthetic/authorize` | Autorizar un punto de inyección: `subject_id`, `system_id`, `point`, `method`, `revert_procedure` | D · 2FA |
| `POST /api/v1/synthetic/{injection_id}/confirm-injection` | El cliente confirma que inyectó | M |
| `POST /api/v1/synthetic/{injection_id}/confirm-exercise` | El cliente confirma que el sujeto ejerció un derecho: `requested_at`, `answered_at`, `right` | M |
| `POST /api/v1/synthetic/{injection_id}/confirm-revert` | El cliente confirma que dejó la fuente como estaba | M |

Quien autoriza no puede confirmar.

### 5.9 Asistente

| Método y ruta | Para qué | Roles |
|---|---|---|
| `POST /api/v1/assistant/ask` | Pregunta en `{"question"}`. Responde con citas numeradas o con un rehúso honesto | A M D |

Cada `[n]` del texto remite a una fuente de la respuesta. Un rehúso se enseña como tal. Sin modelo local responde `503` y con el cupo agotado `429`: el chat debe decirlo y seguir usable. El pie debe recordar que las respuestas no son veredictos de conformidad.

### 5.10 Integraciones, operación y soporte (administración)

| Método y ruta | Para qué | Roles |
|---|---|---|
| `GET /api/v1/webhooks` · `POST /api/v1/webhooks` | Suscripciones hacia el ITSM: `url`, `events` (`finding_opened`, `campaign_sealed`, `approval_requested`), `secret`, `template` | A (crear: 2FA) |
| `GET /api/v1/webhooks/{id}/deliveries` | Entregas y reintentos | A |
| `GET /api/v1/operations/status` | Los ocho semáforos del appliance y las alertas activas, cada una con su runbook | A R |
| `GET /api/v1/operations/capacity` | Posición frente a la talla y serie de 13 meses | A R |
| `GET /api/v1/operations/runbooks/{runbook_id}` | Texto de un runbook en Markdown | A R |
| `GET /api/v1/security/events` | Registro de seguridad | A R |
| `POST /api/v1/support/diagnostics` · `GET …/{id}` · `POST …/{id}/package` | Paquete de diagnóstico: pedirlo, revisarlo en claro y cifrarlo para soporte (esto último, 2FA) | A |
| `POST /api/v1/system/updates` | Verificar y encolar una actualización | A · 2FA |
| `POST /api/v1/airgap/imports` · `POST /api/v1/airgap/exports` | Esclusa del appliance aislado | A · 2FA |

## 6. Flujos de trabajo

### 6.1 Revisión del inventario (DPO)

1. `GET /inventory/coverage` para el panorama por sistema.
2. `GET /inventory/review-queue` para las columnas pendientes.
3. `GET /inventory/nodes/{node_key}` para el contexto de cada una.
4. `POST /inventory/review-queue/{node_key}` con `accept`, `reject` o `correct` (2FA). Con `accept`, enviar la `category` que se enseñó.

### 6.2 De la campaña al cierre verificado de un hallazgo

1. **M** `POST /campaigns` → `planned`.
2. **M** `POST /campaigns/{id}/launch` → el motor prepara el plan (`pinned`) y se para en `start`.
3. **Todos** `GET /campaigns/{id}/plan` y `GET /campaigns/{id}/gates`: lo que se va a preguntar y lo que falta aprobar. Mientras el plan se prepara, `/plan` da `409` y `/progress` dice `preparing`.
4. **D** `POST /campaigns/{id}/gates/start/approve` (2FA). Si hay muestreo, `sampling` pide dos DPO distintos.
5. **Todos** `GET /campaigns/{id}/progress` cada pocos segundos mientras `status` sea `running`: `done` sobre `total`.
6. **Todos** `GET /findings?campaign_id={id}` y `GET /findings/{id}`.
7. **D** `transition` a `in_remediation` y, cuando se corrija, a `pending_verification` (2FA).
8. **M** `POST /findings/{id}/verify` → la reejecución lo deja en `closed_compliant` o `reopened`.
9. Cuando la campaña está `sealed`: evidencia (§5.6) y credencial (§5.7).

Alternativa en el paso 7: **D** `transition` a `risk_accepted` con justificación y caducidad.

### 6.3 Expediente y credencial (DPO)

1. `GET /evidence/{campaign_id}/chain` para comprobar la cadena.
2. `GET /evidence/{campaign_id}/dossier.pdf` para descargar el expediente.
3. `GET /credentials/preview?campaign_id=` para la vista previa.
4. `POST /credentials` con el `dossier_sha256` de esa vista previa (2FA).

## 7. Qué debe cumplir el front

Lo que la consola de la Fase 08 ya resolvía y el front real también debe cumplir:

- Token de acceso solo en memoria. Nada de la sesión en `localStorage`.
- Castellano en toda la interfaz (P-18) y accesibilidad EN 301 549: contraste AA y foco visible.
- Sin recursos de un CDN en tiempo de ejecución si el front se instala en el appliance aislado.
- No ofrecer acciones que el rol o el estado no permiten; usar `allowed_transitions` y las compuertas que devuelve la API.
- Enseñar la evidencia como es: una firma de desarrollo, un sello en cola o una credencial no acreditada se dicen tal cual.

## 8. Material de apoyo

- **Contrato:** `services/api/openapi.json`. De él se pueden generar tipos, por ejemplo con `openapi-typescript`, como hacía la consola.
- **Matriz de permisos:** `services/api/argos_api/authz/permissions.yaml`.
- **Colección de Postman:** `tools/postman/ARGOS-API-v1.postman_collection.json`, con tokens automáticos por rol para el entorno de desarrollo.
- **Referencia de implementación:** la consola de la Fase 08 sigue en `console/` como código, aunque la API ya no la sirva. `console/src/auth/` (PKCE y sesión) y `console/src/api/client.ts` (renovación con un solo reintento) resuelven lo de §2.

## Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1.0 | 2026-09-29 | Primera versión, con la retirada de la consola de la API. Borrador hasta que la API admita otros orígenes |
| 0.2.0 | 2026-09-29 | La API admite el front en otro dominio (C-03): orígenes permitidos, CORS, cookie `SameSite=None`, cabecera `X-Argos-Session` y qué hacer si el navegador bloquea la cookie |
| 0.3.0 | 2026-10-05 | Direcciones del banco de pruebas, origen admitido y túnel mientras los puertos sigan cerrados (K-08) |
