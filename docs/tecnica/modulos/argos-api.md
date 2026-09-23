---
id: MOD-argos-api
kind: module
title: API única autenticada v1 (argos-api)
module: argos-api
phases: ["08"]
version: 0.25.0-alpha
commit: de1f1d3
date: 2026-09-23
status: current
confidentiality: client
---

# API única autenticada v1 (argos-api)

## 1. Propósito

Es la única puerta autenticada a ARGOS: sistemas, inventario, campañas, hallazgos, evidencia, credenciales, asistente, aprobaciones y suscripciones. No hay rutas reservadas a la consola; lo que hace la consola lo puede hacer la integración del cliente con el mismo contrato y la misma autorización. Implementa ARG-071 (pliego P-18, P-19, P-20) y aplica el ADR-0012.

## 2. Alcance y límites

- **Hace:** publicar el contrato de la v1, resolver las peticiones llamando a las librerías del dominio y dejar asiento en el diario de toda mutación (esto último, desde F08-03).
- **No hace:** no escribe SQL sobre tablas de otras fases; no expone material público (eso es `evidence-api` y el comprobador, que siguen siendo servicios aparte).
- **Estado:** implementados sistemas e inventario (F08-04), campañas con su plan previo y compuertas (F08-05), hallazgos con remediación verificada (F08-06), evidencia y credenciales (F08-07), el asistente (F08-08) y los webhooks hacia el ITSM (F08-09). Queda una sola ruta declarada sin comportamiento: `GET /approvals` (lo pendiente de aprobar por esta persona en todas sus campañas) valida permiso y paginación, pero responde `501`; las compuertas de cada campaña sí se sirven en `GET /campaigns/{id}/gates`.

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
| Idempotencia real | `argos.api_idempotency` guarda la respuesta por (actor, clave); repetirla la devuelve sin volver a ejecutar, y la misma clave con otro cuerpo o en otra ruta es `409`. La clave se reserva antes de ejecutar, después del guardián de permisos: de dos peticiones iguales a la vez, una se ejecuta y la otra recibe `409`; si la petición falla, la clave queda libre (F09-26) |
| Auditoría (P-19) | Toda mutación con respuesta correcta deja un asiento `api.mutation` en el diario con actor, método, ruta y estado |
| Sesión | `POST /auth/session` abre la sesión de la consola desde el código y el verificador PKCE (`create_app(code_exchanger=...)`); `POST /auth/refresh` la renueva. El token de refresco vive en una cookie `HttpOnly`, `Secure`, `SameSite=Strict` y `Path=/api/v1/auth/refresh`; la respuesta solo devuelve el de acceso |

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función pública | `app.create_app(validator=None) -> FastAPI` | La aplicación; sin validador, toda ruta autenticada responde `401` |
| Contrato | `services/api/openapi.json` | OpenAPI 3.1 de la v1, versionado y comprobado en CI |
| Herramienta | `tools/api_contract.py [--check]` | Genera el contrato o comprueba que el fichero está al día |
| Rutas | `/api/v1/{systems,inventory,campaigns,findings,evidence,credentials,assistant,approvals,webhooks,auth}` | 34 operaciones declaradas; ver el contrato |
| Salud | `GET /health` | Sin token |
| Recursos vivos | `GET /systems`, `GET /inventory/coverage`, `GET /inventory/nodes/{node_key}`, `GET /inventory/review-queue`, `POST /inventory/review-queue/{node_key}` | Llaman a `argos_inventory`; ningún router escribe SQL propio |
| Campañas | `POST /campaigns` (idempotente), `GET /campaigns`, `GET /campaigns/{id}`, `POST /campaigns/{id}/launch`, `GET /campaigns/{id}/plan`, `GET /campaigns/{id}/progress`, `GET /campaigns/{id}/gates`, `POST /campaigns/{id}/gates/{gate}/approve` | Llaman a `argos_challenges.store`; el plan previo es la lista literal de unidades y lo no verificable, y existe desde que la campaña está preparada (`409` antes) |
| Hallazgos | `GET /findings` (peor primero, filtros `status`, `severity`, `campaign_id`), `GET /findings/{id}`, `POST /findings/{id}/transition`, `POST /findings/{id}/verify` | El detalle trae el porqué completo —veredicto con sus valores, declaración muestral, asiento del diario de la consulta y la obligación con su artículo—, su historia en el diario (`history`) y `allowed_transitions`, para que la consola no duplique la máquina de estados. `closed_compliant` y `reopened` no se alcanzan por transición: solo `verify`, que lanza la reejecución de ARG-049 |
| Evidencia | `GET /evidence/{id}/chain`, `/artifacts`, `/artifacts/{verdict_id}`, `/journal/{seq}`, `/dossier.json`, `/dossier.pdf`, `/bundle` | La cadena con su estado real (firma con su marca `non_production`, sello en cola o sellado con su política), cada artefacto con su prueba de inclusión contra la raíz firmada, el asiento del diario que cita un veredicto de la campaña (solo esos: no es una ventana al diario entero) y el expediente en sus bytes exactos (cabecera `X-Dossier-Sha256`). Cada descarga del expediente o del paquete deja un asiento `evidence.download` con quién |
| Credenciales | `GET /credentials/preview`, `POST /credentials`, `GET /credentials/{id}`, `POST /credentials/{id}/revoke` | Emitir es un acto explícito de `dpo_reviewer`: la vista previa muestra el sujeto exacto y `withheld`, lo que se queda en el expediente, y la emisión nombra por su hash el expediente que se vio; si cambió entremedias, `409`. Revocar exige motivo |
| Asistente | `POST /assistant/ask` | Reenvía la pregunta al gateway de IA **por HTTP** —el único servicio al que llama la API (ADR-0012)— y devuelve respuesta, citas, herramientas consultadas, `complete`, `refused` y `fragments` (los fragmentos normativos recuperados, para desplegar las citas o juzgar un rehúso); siempre con `assisted: true` y el aviso de que no es un veredicto. Sin modelo local, `503` con el motivo |
| Cliente | `assistant.AssistantClient(base_url)` y `create_app(assistant=...)` | Sin cliente, la ruta responde `503`; un gateway inalcanzable, también. La API no importa `argos_ai`: un test lo impide |
| Webhooks | `POST /webhooks`, `GET /webhooks`, `GET /webhooks/{id}/deliveries` | Solo `platform_admin`. El secreto lo elige el cliente, va al almacén de secretos (`webhooks/<id>`) y no sale nunca en una respuesta, en la base de datos ni en el diario. La bandeja guarda cada intento: estado, intentos, último código y la **clase** de error (`destination_refused`, `timeout`, `connection`, `transport`), nunca el texto de la otra parte. El destino es solo `https` y no puede apuntar dentro del appliance (ver Seguridad) |
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

El proceso (`python -m argos_api.main`) lee `ARGOS_DATABASE_URL`, `ARGOS_TEMPORAL_ADDRESS`, `ARGOS_VAULT_ADDR`/`ARGOS_VAULT_TOKEN`, `ARGOS_OIDC_ISSUER` y `ARGOS_OIDC_AUDIENCE`, la configuración de evidencia (`ARGOS_EVIDENCE_*`), `ARGOS_AI_GATEWAY_URL` (el asistente; sin ella, la ruta responde 503) y `ARGOS_CONSOLE_DIR` (los estáticos de la consola, `/app/console` en la imagen). `ARGOS_API_BIND` existe solo para el contenedor: docker publica el puerto en `127.0.0.1`. Desde F09-05, `ARGOS_DATABASE_URL` no lleva usuario (`postgresql://postgres:5432/argos?service=argos`), y `ARGOS_DATABASE_VAULT_ROLE` (`svc-api` y `svc-webhook`) con `ARGOS_VAULT_APPROLE_DIR` dicen de dónde sale la credencial. La contraseña de la base llega en un fichero, `ARGOS_DATABASE_PASSWORD_FILE` (en desarrollo, `/run/secrets/db-api`, que genera `tools/dev_db_users.py`), y no en la cadena de conexión.

## 6. Seguridad y tratamiento de datos

- **Ninguna acción humana sin asiento** (F09-26, SEC-029, SEC-030, SEC-040, SEC-044): el asiento `api.mutation` se escribe antes de guardar la respuesta idempotente; lanzar una campaña deja `campaign.launch` y emitir una credencial deja `credential.issued`, los dos con la persona y los identificadores; una respuesta guardada nunca se entrega sin pasar antes el guardián de permisos, y validar el token no bloquea el bucle de eventos.
- **Postura del contenedor** (F09-03, ARG-084, P-22): corre como `10001:10001`, sin capacidades (`cap_drop: [ALL]`), con la raíz de solo lectura y `/tmp` en `tmpfs`, sin escalada (`no-new-privileges`) y con el perfil seccomp por defecto de Docker. La imagen no lleva `bash`. En el compose lo exige `tests/security/test_compose_posture.py`, y `tests/integration/test_container_posture.py` lo comprueba dentro del contenedor en marcha.
- **Base de datos con mínimo privilegio** (F09-04, ARG-085): la API se conecta como `login_api`, miembro del rol `svc_api`, y el worker de webhooks como `login_webhook`, miembro de `svc_webhook` (migración `0033`), y nunca como superusuario. El rol tiene solo las tablas y operaciones que usa su código; el diario se escribe únicamente con `argos.journal_append()`. Lo comprueban `tests/integration/test_service_roles.py` (la matriz `tests/fixtures/db_access_matrix.yaml` y el usuario de cada contenedor en marcha).
- **Credencial de base de datos efímera** (F09-05, ARG-085): el servicio entra con un usuario que Vault crea para él, miembro de ``svc_api` (el worker de webhooks, de `svc_webhook`)`, válido 24 h y borrado al vencer. Lo renueva en caliente `argos_common.dynamic_db`. El AppRole con el que lo pide llega por volumen y no aparece en `docker inspect`.
- Ninguna ruta autenticada se resuelve sin un token válido con rol del realm y sin el permiso que la ruta declara.
- **Integraciones:** `webhooks.read` pasa a ser solo de `platform_admin` (F08-09); el auditor ya no ve la configuración de las integraciones.
- **Emisión de credenciales:** pasa de `campaign_manager` a `dpo_reviewer` (F08-07): es el DPO quien firma lo que se afirma ante terceros, después de leer la vista previa.
- **Separación de deberes:** quien planifica y lanza (`campaign_manager`) no aprueba compuertas ni mueve hallazgos; `platform_admin` opera la plataforma (integraciones, revocación) y no aprueba ni juzga; `read_only_auditor` solo tiene permisos `.read`. Aceptar un riesgo es de `dpo_reviewer` y exige justificación escrita. El doble control del muestreo sigue siendo el de ARG-047, en el motor de campañas.
- Los cuerpos se validan con Pydantic y un cuerpo inválido sale como `422` en formato problema, sin filtrar trazas.
- Decisiones aplicables: ADR-0012 (API única), ADR-0013 (consola), nota de desviación ARG-071-080 (identificadores en inglés y sin `INSERT` propios).
- **Entradas acotadas** (auditoría del 2026-09-18, trasladada en F09-17): identificadores de ruta tipados como UUID, textos libres de 2000 caracteres como máximo, `scope` de campaña de 16 KiB y nombre de compuerta `^[a-z_]{1,32}$`; lo que no cumple responde 422 sin tocar la base.
- **Errores de la base sin detalle:** un `psycopg.Error` responde 503 problem+json («the store is not available») y solo su tipo queda en el log; el mensaje del driver nombra host, SQL o restricción.
- **Mapa de rutas solo en desarrollo:** `/api/v1/docs` y `/api/v1/openapi.json` se sirven con `ARGOS_ENVIRONMENT=development`; el contrato versionado se sigue generando de `openapi()`.
- **Sujeto sintético ligado a su campaña:** la autorización pasa el `campaign_id` de la ruta y el dominio rechaza un sujeto de otra campaña.
- **Señal a campañas sin workflow propio** (F09-23): `TemporalCampaigns.signal` ignora que no exista `campaign-<id>`, porque una campaña de subsanación consulta sus compuertas por su cuenta.
- **Webhooks sin destinos internos** (F09-30, SEC-031): `webhooks.destination.check_destination` exige `https`, rechaza los nombres de los servicios del appliance y `localhost`, resuelve el nombre y rechaza cualquier dirección que no sea pública (loopback, privada, link-local, reservada). Se comprueba al suscribir (422) y otra vez antes de cada entrega (queda `failed` con `destination_refused`, sin enviar nada). La excepción para el ITSM del cliente en su red privada la escribe quien instala, en `ARGOS_WEBHOOK_ALLOWED_TARGETS` (nombres o redes, separados por comas).
- **Sesión que se cierra** (F09-30, SEC-041): `POST /auth/logout` revoca el refresco en Keycloak y borra la cookie. La cookie de refresco es de sesión (sin `Max-Age`: muere con el navegador) y su ruta es `/api/v1/auth`, para que la lean el refresco y el cierre. Un refresco que el realm rechaza responde 401 problem+json, y una respuesta del realm que no es JSON (un proxy que contesta HTML) es un rechazo, no un error 500.
- **Cabeceras de seguridad** (F09-30, SEC-046): toda respuesta, de la consola y de la API, lleva `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff` y `Referrer-Policy: same-origin`. Solo la página de `/api/v1/docs` de desarrollo, que carga de una CDN, queda fuera.
- **Límites de texto** (F09-30, SEC-045): `Revocation.reason` y `ReviewDecision.note` hasta 2000 caracteres, `Exercise.right` hasta 40 y la cabecera `Idempotency-Key` de 1 a 128 letras, cifras, `-` o `_` (F09-26, SEC-029: fuera de ese alfabeto, `400` sin ejecutar nada).
- **Quién pregunta al asistente** (F09-29, SEC-043): `AssistantClient.ask(question, person)` envía al gateway el actor autenticado (`user:<sub>`), y la cuota del asistente se cuenta por persona.
- **Fechas del cliente en el ejercicio de un derecho** (F09-27, SEC-014): `POST /synthetic/{id}/confirm-exercise` exige `requested_at` y `answered_at` con zona horaria. El plazo se mide entre ambas, nunca con la hora de la petición; unas fechas futuras o desordenadas responden 409.
- **Roles incompatibles** (F09-24, SEC-008): `permissions.yaml` declara `_incompatible_roles` (`campaign_manager` con `dpo_reviewer`), y el guardián de permisos rechaza con 403 en toda ruta un token que los traiga juntos. `risk_expiry` fuera de rango responde 422.

## 7. Operación

Una sola imagen (`services/api/Dockerfile`) construye la consola con su fichero de bloqueo y la copia junto a la API: un origen, sin CDN, como exige un equipo aislado. `make dev` levanta el servicio `api` en `127.0.0.1:8000` —con healthcheck sobre `/health`— y `webhook-worker`, que entrega los webhooks (cola `argos-webhooks`) y escucha el bus con un durable por asunto. El servicio `api` está en las redes `default`, `ai` (el gateway, el único al que llama) y `evidence`; el worker de campañas no está en `ai`.

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

- **Webhooks y *DNS rebinding*:** el destino se resuelve y se comprueba al suscribir y justo antes de cada entrega, pero la conexión vuelve a resolver el nombre. Un DNS que cambie de respuesta entre esas dos resoluciones podría llevar una entrega a una dirección interna. Cerrarlo del todo exige fijar la IP en la conexión HTTPS con su SNI y la verificación del certificado por nombre.
- La API de campañas de la Fase 05 (`challenge-api`) está retirada: sus rutas viven aquí desde F08-17.
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
| 0.10.0-alpha | 2026-09-21 | `POST /auth/session` para abrir la sesión de la consola con PKCE; el refresco queda en la cookie | F08-10 |
| 0.11.0-alpha | 2026-09-21 | La cola de revisión admite `correct` con `category` (rechaza la propuesta y clasifica la columna); el detalle de nodo trae `deltas` | F08-11 |
| 0.12.0-alpha | 2026-09-22 | El detalle de hallazgo trae `history` y la declaración muestral del veredicto, que antes llegaba vacía | F08-13 |
| 0.13.0-alpha | 2026-09-22 | `GET /evidence/{id}/journal/{seq}` (asiento citado por un veredicto de la campaña) y `withheld` en la vista previa de la credencial | F08-14 |
| 0.14.0-alpha | 2026-09-22 | `POST /assistant/ask` devuelve `refused` y `fragments` | F08-15 |
| 0.15.0-alpha | 2026-09-22 | Proceso `argos_api.main` con todo cableado (realm, Temporal, evidencia, gateway y Vault), consola servida como estáticos del mismo origen, veredictos de campaña, sujeto sintético y reejecución de subsanación; retirada de `challenge-api` | F08-17 |
| 0.16.0-alpha | 2026-09-23 | Endurecimiento de la auditoría del 2026-09-18 trasladado desde la API de campañas retirada: entradas acotadas, 503 sin detalle ante errores de la base, `/docs` y contrato servido solo en desarrollo, y autorización del sujeto sintético ligada a su campaña | F09-17 |
| 0.17.0-alpha | 2026-09-23 | La señal de aprobación no falla con campañas de subsanación | F09-23 |
| 0.18.0-alpha | 2026-09-23 | `_incompatible_roles` en la matriz y tope de la aceptación de riesgo | F09-24 |
| 0.19.0-alpha | 2026-09-23 | `confirm-exercise` recibe las fechas de solicitud y respuesta del cliente | F09-27 |
| 0.20.0-alpha | 2026-09-23 | El asistente recibe quién pregunta para su cuota por persona | F09-29 |
| 0.21.0-alpha | 2026-09-23 | Webhooks sin destinos internos y con clase de error, `POST /auth/logout` con cookie de sesión, cabeceras de seguridad, límites de texto y refresco rechazado como 401 | F09-30 |
| 0.22.0-alpha | 2026-09-23 | Contenedor con la postura restringida de ARG-084 (API y worker de webhooks) | F09-03 |
| 0.23.0-alpha | 2026-09-23 | Usuario de base `login_api` en `svc_api` (y `login_webhook` en `svc_webhook`); contraseña en fichero de secreto | F09-04 (ARG-085) |
| 0.24.0-alpha | 2026-09-23 | Idempotencia tras el guardián, con reserva, clave acotada y huella por ruta real; asientos `campaign.launch` y `credential.issued` con la persona | F09-26 (ARG-005, ARG-071) |
| 0.25.0-alpha | 2026-09-23 | Usuario de base efímero de Vault (`svc-api`, `svc-webhook`), renovado en caliente | F09-05 (ARG-085) |
