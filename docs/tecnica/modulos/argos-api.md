---
id: MOD-argos-api
kind: module
title: API única autenticada v1 (argos-api)
module: argos-api
phases: ["08"]
version: 0.9.0-alpha
commit: fc4ff01
date: 2026-09-20
status: current
confidentiality: client
---

# API única autenticada v1 (argos-api)

## 1. Propósito

Es la única puerta autenticada a ARGOS: sistemas, inventario, campañas, hallazgos, evidencia, credenciales, asistente, aprobaciones y suscripciones. No hay rutas reservadas a la consola; lo que hace la consola lo puede hacer la integración del cliente con el mismo contrato y la misma autorización. Implementa ARG-071 (pliego P-18, P-19, P-20) y aplica el ADR-0012.

## 2. Alcance y límites

- **Hace:** publicar el contrato de la v1, resolver las peticiones llamando a las librerías del dominio y dejar asiento en el diario de toda mutación (esto último, desde F08-03).
- **No hace:** no escribe SQL sobre tablas de otras fases; no expone material público (eso es `evidence-api` y el comprobador, que siguen siendo servicios aparte).
- **Estado:** implementados sistemas e inventario (F08-04) campañas con su plan previo y compuertas (F08-05) hallazgos con remediación verificada (F08-06) evidencia y credenciales (F08-07) el asistente (F08-08) y los webhooks hacia el ITSM (F08-09); el resto de rutas están declaradas y validan sus parámetros, pero devuelven `501` hasta su tarea.

## 3. Arquitectura

- `argos_api.app.create_app(validator)`: monta `/health`, los routers de cada recurso bajo `/api/v1` y los manejadores de error; expone el contrato en `/api/v1/openapi.json`.
- `argos_api.routers.*`: un módulo por recurso (`systems`, `inventory`, `campaigns`, `findings`, `evidence`, `credentials`, `assistant`, `approvals`, `webhooks`, `session`).
- `argos_api.http`: el problema RFC 9457, la cabecera de idempotencia y el `501` de lo que aún no está.
- `argos_api.paging`: el cursor opaco (`created_at`, `id`), su validación en la dependencia de paginación y el gemelo en memoria del predicado SQL (`apply_keyset`), para que la consulta y la prueba digan lo mismo.
- `argos_api.core`: `CoreRoute`, la clase de ruta que envuelve a todas. Es clase de ruta y no middleware a propósito: un middleware corre antes de resolver las dependencias y no sabe todavía quién llama. Aquí la identidad ya está resuelta, así que el asiento del diario lleva el actor real y una llamada denegada no deja rastro de algo que no ocurrió.
- `argos_api.auth`: exige un token del realm `argos` con algún rol de ARGOS.
- `argos_api.authz`: cada ruta declara un permiso `recurso.acción` y la matriz `permissions.yaml` dice qué roles lo tienen. Un permiso que la matriz no declara es un error de arranque, no una puerta abierta.
- El contrato **se genera del código**: `tools/api_contract.py` lo escribe en `services/api/openapi.json` y `--check` falla si divergen. `make api-contract` está en `make check` y en el CI.

### Decisiones transversales

| Decisión | Cómo se materializa |
|---|---|
| Versión en la ruta | Todo cuelga de `/api/v1`; solo `/health` queda fuera |
| Errores | `application/problem+json` (RFC 9457) en **todos** los códigos ≥ 400, incluido el 404 de una ruta inexistente |
| Paginación | `cursor` opaco y `limit` (1…200, por defecto 50); nunca `offset` |
| Idempotencia | `Idempotency-Key` en los POST que crean (campañas, credenciales, suscripciones) |
| Autenticación | `Bearer` del Keycloak del appliance; sin token, `401` con `WWW-Authenticate` |
| Autorización | Denegación por defecto: `require_perm("recurso.acción")` en cada ruta contra `permissions.yaml` |
| Idempotencia real | `argos.api_idempotency` guarda la respuesta por (actor, clave); repetirla la devuelve sin volver a ejecutar, y la misma clave con otro cuerpo es `409` |
| Auditoría (P-19) | Toda mutación con respuesta correcta deja un asiento `api.mutation` en el diario con actor, método, ruta y estado |
| Sesión | El token de refresco vive en una cookie `HttpOnly`, `Secure`, `SameSite=Strict` y `Path=/api/v1/auth/refresh`; la respuesta solo devuelve el de acceso |

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función pública | `app.create_app(validator=None) -> FastAPI` | La aplicación; sin validador, toda ruta autenticada responde `401` |
| Contrato | `services/api/openapi.json` | OpenAPI 3.1 de la v1, versionado y comprobado en CI |
| Herramienta | `tools/api_contract.py [--check]` | Genera el contrato o comprueba que el fichero está al día |
| Rutas | `/api/v1/{systems,inventory,campaigns,findings,evidence,credentials,assistant,approvals,webhooks,auth}` | 33 operaciones declaradas; ver el contrato |
| Salud | `GET /health` | Sin token |
| Recursos vivos | `GET /systems`, `GET /inventory/coverage`, `GET /inventory/nodes/{node_key}`, `GET /inventory/review-queue`, `POST /inventory/review-queue/{node_key}` | Llaman a `argos_inventory`; ningún router escribe SQL propio |
| Campañas | `POST /campaigns` (idempotente), `GET /campaigns`, `GET /campaigns/{id}`, `POST /campaigns/{id}/launch`, `GET /campaigns/{id}/plan`, `GET /campaigns/{id}/progress`, `GET /campaigns/{id}/gates`, `POST /campaigns/{id}/gates/{gate}/approve` | Llaman a `argos_challenges.store`; el plan previo es la lista literal de unidades y lo no verificable, y existe desde que la campaña está preparada (`409` antes) |
| Hallazgos | `GET /findings` (peor primero, filtros `status`, `severity`, `campaign_id`), `GET /findings/{id}`, `POST /findings/{id}/transition`, `POST /findings/{id}/verify` | El detalle trae el porqué completo —veredicto con sus valores, declaración muestral, asiento del diario de la consulta y la obligación con su artículo— y `allowed_transitions`, para que la consola no duplique la máquina de estados. `closed_compliant` y `reopened` no se alcanzan por transición: solo `verify`, que lanza la reejecución de ARG-049 |
| Evidencia | `GET /evidence/{id}/chain`, `/artifacts`, `/artifacts/{verdict_id}`, `/dossier.json`, `/dossier.pdf`, `/bundle` | La cadena con su estado real (firma con su marca `non_production`, sello en cola o sellado con su política), cada artefacto con su prueba de inclusión contra la raíz firmada, y el expediente en sus bytes exactos (cabecera `X-Dossier-Sha256`). Cada descarga del expediente o del paquete deja un asiento `evidence.download` con quién |
| Credenciales | `GET /credentials/preview`, `POST /credentials`, `GET /credentials/{id}`, `POST /credentials/{id}/revoke` | Emitir es un acto explícito de `dpo_reviewer`: la vista previa muestra el sujeto exacto y la emisión nombra por su hash el expediente que se vio; si cambió entremedias, `409`. Revocar exige motivo |
| Asistente | `POST /assistant/ask` | Reenvía la pregunta al gateway de IA **por HTTP** —el único servicio al que llama la API (ADR-0012)— y devuelve respuesta, citas, herramientas consultadas y `complete`; siempre con `assisted: true` y el aviso de que no es un veredicto. Sin modelo local, `503` con el motivo |
| Cliente | `assistant.AssistantClient(base_url)` y `create_app(assistant=...)` | Sin cliente, la ruta responde `503`; un gateway inalcanzable, también. La API no importa `argos_ai`: un test lo impide |
| Webhooks | `POST /webhooks`, `GET /webhooks`, `GET /webhooks/{id}/deliveries` | Solo `platform_admin`. El secreto lo elige el cliente, va al almacén de secretos (`webhooks/<id>`) y no sale nunca en una respuesta, en la base de datos ni en el diario. La bandeja guarda cada intento: estado, intentos, último código y error |
| Firma | `X-Argos-Signature: t=<segundos>,v1=<hex>` | HMAC-SHA256 con el secreto sobre `t`, un punto y los bytes exactos del cuerpo; el receptor rechaza una marca con más de 300 s (`webhooks.signing.verify` es lo que haría él). `X-Argos-Event` lleva el tipo |
| Plantillas | `argos_api/webhooks/templates.yaml` | ServiceNow, Jira y genérico como **configuración**: marcadores `{campo}`, el evento entero y búsqueda por campo; añadir un destino no toca código |
| Entrega | `webhooks.workflow.WebhookDelivery` + `webhooks.dispatch.WebhookActivities` (cola `argos-webhooks`) | Reintentos con retroceso exponencial (1, 2, 4… s, 8 intentos por defecto) |
| Suscriptor | `webhooks.subscriber.on_event(subject, dsn, start)` | Hallazgo abierto, campaña sellada y compuerta pendiente crean una entrega por suscripción y lanzan su workflow. El worker y la suscripción al bus se cablean con el contenedor (F08-17) |
| Servicio | `create_app(evidence=EvidenceActivities)` | El dominio de evidencia en el mismo proceso (ADR-0012); sin él, las rutas responden `503` |
| Protocolo | `runner.CampaignRunner` (`start`, `signal`, `progress`, `remediate`) | Lo que la API pide a Temporal; `create_app(campaign_runner=...)`. La implementación sobre el cliente de Temporal se cablea con el contenedor (F08-17) |
| Grafo | `POST /api/v1/inventory/graph` | GraphQL de ARG-029 montado dentro de la v1, con el permiso `inventory.read` delante |
| Clase de ruta | `core.CoreRoute` | Idempotencia y asiento en el diario alrededor de cada ruta |
| Función pública | `paging.paginate(rows, limit) -> Page` y `paging.apply_keyset(rows, position)` | Página y cursor; `position_of()` valida el cursor y un cursor ajeno es `400` |
| Migración | `0028_api_idempotency.sql` | Estado operativo, no evidencia: lo que hizo la mutación está en el diario |
| Matriz | `argos_api/authz/permissions.yaml` | Permiso → roles del realm, versionada y revisable por el cliente |
| Función pública | `authz.require_perm(permiso) -> PermissionGuard` | Dependencia de ruta; permiso no declarado = error de arranque |
| Función pública | `authz.load_matrix(path) -> dict[str, frozenset[str]]` | Rechaza roles fuera del realm y permisos sin roles |

## 5. Configuración

Por ahora, el emisor y la audiencia OIDC que recibe el validador (`ARGOS_OIDC_ISSUER`, `ARGOS_OIDC_AUDIENCE`, ya existentes). El contenedor y su punto de entrada llegan con F08-17.

## 6. Seguridad y tratamiento de datos

- Ninguna ruta autenticada se resuelve sin un token válido con rol del realm y sin el permiso que la ruta declara.
- **Integraciones:** `webhooks.read` pasa a ser solo de `platform_admin` (F08-09); el auditor ya no ve la configuración de las integraciones.
- **Emisión de credenciales:** pasa de `campaign_manager` a `dpo_reviewer` (F08-07): es el DPO quien firma lo que se afirma ante terceros, después de leer la vista previa.
- **Separación de deberes:** quien planifica y lanza (`campaign_manager`) no aprueba compuertas ni mueve hallazgos; `platform_admin` opera la plataforma (integraciones, revocación) y no aprueba ni juzga; `read_only_auditor` solo tiene permisos `.read`. Aceptar un riesgo es de `dpo_reviewer` y exige justificación escrita. El doble control del muestreo sigue siendo el de ARG-047, en el motor de campañas.
- Los cuerpos se validan con Pydantic y un cuerpo inválido sale como `422` en formato problema, sin filtrar trazas.
- Decisiones aplicables: ADR-0012 (API única), ADR-0013 (consola), nota de desviación ARG-071-080 (identificadores en inglés y sin `INSERT` propios).

## 7. Operación

En desarrollo, `uv run uvicorn argos_api.app:create_app --factory`. El servicio del `compose` y la consola servida como estáticos llegan en F08-17.

## 8. Verificación

- `services/api/tests/test_webhooks_pure.py`: un receptor escrito a mano desde la documentación verifica la firma; un cuerpo cambiado, otro secreto o una marca antigua no verifican; las plantillas salen del YAML.
- `tests/integration/test_api_webhooks.py`: el secreto no vuelve nunca (respuesta, tabla, diario) y vive en Vault; plantilla desconocida `422`; solo `platform_admin`; un evento crea una entrega por suscripción a él; reintentos reales en Temporal hasta que llega, o `failed` al agotarlos, con la bandeja diciendo cuántos y con qué código; el suscriptor convierte un hallazgo en entregas; la compuerta pendiente se anuncia una vez.
- `tests/integration/test_api_assistant.py`: con el gateway real montado por transporte ASGI y un modelo simulado, la respuesta trae citas y herramientas; sin base suficiente lo dice (`complete: false`); sin modelo local, sin gateway o sin cliente, `503` con el motivo; un auditor no gasta la cuota del modelo.
- `services/api/tests/test_no_ai_imports_pure.py`: ningún módulo de la API importa la capa de IA.
- `tests/integration/test_api_evidence.py`: cadena con el sello en cola y luego sellada con su política, artefactos paginados cuya prueba verifica contra la raíz firmada, expediente JSON y PDF y paquete descargados con asiento de quién, `404` sin expediente, lo emitido es lo que mostró la vista previa, no se emite sobre un expediente que ya no es el vigente, emitir es del DPO, y una credencial revocada lo dice con su motivo.
- `tests/integration/test_api_findings.py`: la lista ordena de peor a mejor y filtra, el detalle trae el porqué completo, una persona no cierra ni reabre (ni por la API ni en el dominio), la aceptación de riesgo exige nota y caducidad, `verify` solo sobre lo que espera verificación y la reejecución de un hallazgo trae solo su unidad.
- `tests/integration/test_api_campaigns.py`: creación que sobrevive a un reintento, lectura y `404`, lanzamiento a Temporal (y `503` sin runner), plan previo con lo no verificable en su sección y `409` antes de preparar, progreso del workflow, compuerta de una aprobación, muestreo con dos personas distintas y `409` si repite la misma, y con tokens reales de Keycloak el diario dice quién aprobó.
- `tests/integration/test_api_inventory.py`: listado paginado, cursor ajeno rechazado, cobertura con lo pendiente de revisar, nodo con su vecindario y `404` si no existe, la cola de revisión, y que aceptar una columna escribe la arista humana, el asiento `inventory.review` y la etiqueta que lee la calibración; una columna se decide una sola vez y el grafo responde `401`/`403` según la matriz.
- `tests/integration/test_api_core.py`: la misma clave no repite el efecto ni el asiento, la misma clave con otro cuerpo es `409`, sin clave cada llamada es nueva, una llamada denegada no deja asiento, el refresco solo sale de la cookie y **se recorre toda ruta mutadora** comprobando que la que responde correctamente deja su asiento (hoy responden `501`; el test aprieta solo según se implementan).
- `services/api/tests/test_core_pure.py`: el cursor es opaco, uno ajeno se rechaza y la paginación no repite ni salta filas cuando se insertan otras en medio.
- `tests/contract/test_api_authz.py`: las 72 combinaciones de rol × permiso contra la expectativa escrita a mano en `tests/fixtures/authz_matrix.yaml`, que ninguna ruta de la v1 queda sin permiso (salvo el refresco de sesión) y los invariantes de separación de deberes.
- `services/api/tests/test_authz_pure.py`: la matriz sola —carga, roles fuera del realm, permiso sin roles, permiso no declarado y el guardián.
- `tests/contract/test_api_v1.py`: cada recurso declarado, la forma del error, la paginación por cursor, la cabecera de idempotencia, el `401` anónimo y que el fichero versionado es exactamente el generado.
- `make api-contract`, dentro de `make check` y del CI.

## 9. Limitaciones conocidas y pendientes

- Las rutas responden `501` hasta su tarea (F08-04 en adelante); `challenge-api` sigue en pie hasta F08-17.
- El listado de hallazgos pagina por su propio orden (severidad y recurrencia) con el mismo cursor opaco.
- El vecindario de un nodo se devuelve con `limit` y `has_more`, no con cursor: el cursor por desplazamiento del GraphQL es suyo y no se mezcla con el de las listas.
- La tabla de idempotencia no tiene aún purga por retención: hay un índice por `created_at` esperándola (pendiente registrado).
- El montaje de GraphQL bajo `/api/v1/inventory/graph` (ADR-0012 §5) llega con el inventario, en F08-04.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-20 | Contrato OpenAPI v1, esqueleto de rutas y suite de contrato | F08-01 |
| 0.2.0-alpha | 2026-09-20 | Matriz de autorización versionada, denegación por defecto y separación de deberes | F08-02 |
| 0.3.0-alpha | 2026-09-20 | Núcleo: cursor opaco, idempotencia con tabla, auditoría de mutaciones y refresco de sesión | F08-03 |
| 0.4.0-alpha | 2026-09-20 | Sistemas e inventario: cobertura, nodo, cola de revisión y GraphQL montado bajo la misma matriz | F08-04 |
| 0.5.0-alpha | 2026-09-21 | Campañas: creación idempotente, plan previo literal, progreso, lanzamiento y compuertas con doble control | F08-05 |
| 0.6.0-alpha | 2026-09-21 | Hallazgos: porqué completo, transiciones servidas por la API y cierre solo por reejecución | F08-06 |
| 0.7.0-alpha | 2026-09-21 | Evidencia y credenciales: cadena real, prueba de inclusión, descargas auditadas, vista previa y emisión por el DPO | F08-07 |
| 0.8.0-alpha | 2026-09-21 | Asistente por HTTP al gateway de IA, marcado como texto asistido y `503` honesto sin modelo | F08-08 |
| 0.9.0-alpha | 2026-09-21 | Webhooks firmados hacia el ITSM: suscripciones con secreto en Vault, plantillas como configuración, reintentos en Temporal y bandeja de entregas | F08-09 |
