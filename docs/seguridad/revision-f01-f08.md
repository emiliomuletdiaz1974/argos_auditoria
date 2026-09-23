# Revisión de seguridad de las Fases 01 a 08

**Versión:** 1.0 · **Fecha:** 2026-09-23 · **Base:** `main` en `47711f5` (con la auditoría del 2026-09-18 integrada) · **Confidencialidad:** `client`
**Tarea:** F09-02 · **Referencia:** [modelo de amenazas](modelo-amenazas.md)

Tratamos nuestros hallazgos como los de un cliente: cada uno queda **registrado** aquí, se **corrige** en una tarea con un test que lo reproduce primero, y la corrección queda **evidenciada** en el commit y en este registro.

## 1. Cómo se hizo

| Pasada | Qué | Resultado |
|---|---|---|
| Reglas `S` (flake8-bandit) de ruff | Activas desde S1-01 en `make lint`; revisadas las 20 supresiones `noqa: S…` | Todas justificadas: las interpolaciones SQL reciben literales del propio módulo y los subprocesos van sin shell |
| `npm audit` de la consola | Dependencias del frontend | 2 moderadas en `vitest` (dependencia de desarrollo, no viaja en la imagen): SEC-057 |
| Lectura dirigida | Cinco superficies del modelo de amenazas, en paralelo: API y consola; conectores e inventario; gateway de IA; evidencia y firmas; motor de retos y ontología | 56 hallazgos |
| Reproducción | Evasiones del validador SQL (SEC-005, 006, 021), prueba de Merkle con otro tamaño (SEC-039), `did:web` a otro dominio (SEC-038), depuradores y guardarraíles de IA (SEC-032, 034, 035) | Confirmados ejecutando el código |

**Fuera de este registro:**
- Lo que ya tenía tarea al refinar la fase: base de datos con `trust` y superusuario (F09-04), contenedores como root (F09-03), sin MFA (F09-07), tráfico interno en claro (F09-06) y gateway sin autenticación entre servicios (M2, F09-06).
- Los 21 hallazgos de la auditoría del 2026-09-18, corregidos e integrados en F09-17.

**Criterio de severidad:**
- **Alta:** rompe una promesa del producto frente a un adversario del modelo sin requisitos raros. Ejemplos: el comprobador acepta evidencia falsa, ARGOS bloquea un sistema del cliente, se fabrica un veredicto.
- **Media:** exige una posición previa (un rol, acceso a la red interna, un reto aceptado en la biblioteca) o su impacto está acotado.
- **Baja:** endurecimiento, robustez o impacto marginal.

**Verificación:**
- **C** (confirmado): reproducido, o comprobado leyendo el código en esta revisión.
- **L** (leído): identificado leyendo el código por el revisor de su superficie, con archivo y línea.

## 2. Hallazgos

| ID | Hallazgo | Superficie | Sev. | Verif. | Decisión | Tarea |
|---|---|---|---|---|---|---|
| SEC-001 | El comprobador público toma la clave del emisor y las raíces de la TSA del propio bundle: un atacante firma con su clave y obtiene `ok` (`services/verifier/argos_verifier/checks.py:76-80`, `:103`, `:136`) | Comprobador público | Alta | C | Corregir | F09-20 |
| SEC-002 | Sin credencial en el bundle, el contenido del expediente no está autenticado: se cambian veredictos, se recalcula su SHA-256 interno y sale `ok` (`checks.py:88-95`, `:120-127`, `:148-160`) | Comprobador público | Alta | L | Corregir | F09-20 |
| SEC-003 | Denegación de servicio del comprobador: cuerpo *chunked* sin tope, base58 cuadrático sobre valores enormes y gzip de la lista de estado sin límite (`api.py:31-34`, `multibase.py:33`, `status.py:51`) | Comprobador público | Alta | L | Corregir | F09-20 |
| SEC-004 | El presupuesto de carga y el cortacircuitos se crean de nuevo en cada sonda: nunca limitan ni se abren en campañas, reexploraciones ni clasificación (`services/inventory/argos_inventory/discovery/probes.py:74`) | Conectores | Alta | C | Corregir | F09-22 |
| SEC-005 | MySQL/MariaDB: sqlglot descarta como comentario código que el motor ejecuta (`/*! … */`, `--1`): `FOR UPDATE`, `INTO OUTFILE`, `SLEEP` pasan la validación (`connectors/sdk/argos_connector/readonly.py:138`) | Conectores | Alta | C | Corregir | F09-21 |
| SEC-006 | SQL Server: se aceptan pistas de bloqueo (`WITH (TABLOCKX, HOLDLOCK)`) y no hay tiempo máximo de sentencia (`readonly.py`; `connectors/sql/argos_sql/generic.py:204-205`) | Conectores | Alta | C | Corregir | F09-21 |
| SEC-007 | Quien alcance Temporal puede lanzar `SystemRun` con unidades inventadas y el evaluador persiste su veredicto, que después se sella (`workflows.py:72-99`, `activities.py:384-429`, `store.py:123-158`) | Motor de retos | Alta | L | Corregir | F09-23 |
| SEC-008 | Separación de deberes solo por rol: con `campaign_manager` y `dpo_reviewer` a la vez, una persona crea, lanza y aprueba su campaña, cuenta como uno de los dos aprobadores del muestreo y confirma sola el sujeto sintético (`store.py:201-244`, `synthetic.py:236-272`, `authz/enforce.py:50`) | API y motor | Alta | C | Corregir | F09-24 |
| SEC-009 | El doble control depende de `approval_required` y no de que haya muestreo; el lint que lo exige no se ejecuta al cargar la biblioteca; `plan_sampling` no se usa (`activities.py:206`, `library/catalog.py:67-78`) | Motor de retos | Alta | L | Corregir | F09-23 |
| SEC-010 | La reejecución de subsanación no pasa por ninguna compuerta: un `campaign_manager` solo repite sondas de muestreo hasta que una da `compliant` (`workflows.py:213-257`) | Motor de retos | Media | L | Corregir | F09-23 |
| SEC-011 | Retos, políticas Rego, formas SHACL y `data.client` se leen del disco sin verificar firma; la campaña sella como bueno el hash de lo manipulado (`library/catalog.py:67`, `shacl.py:80-84`, `compose.yaml` de OPA) | Motor y ontología | Media | L | Corregir | F09-25 |
| SEC-012 | El `input_map` de un criterio OPA puede fijar el resultado (`result`, `out_of_term`, `max_age_days`) y sus referencias `$client` no se resuelven (`activities.py:387-392`, `compiler.py:143`) | Motor de retos | Media | L | Corregir | F09-23 |
| SEC-013 | El sello no cubre la evidencia que vio OPA, las aprobaciones, el plan de unidades ni los parámetros del cliente; se puede sellar una campaña `failed` (`seal.py:35-78`, `evaluator.py:186`) | Motor de retos | Media | L | Corregir | F09-23 |
| SEC-014 | `access_request_days` mide los clics de confirmación, toma inyecciones de otras campañas y `exercised_at` se puede reescribir (`probes.py:39-45`, `synthetic.py:290-304`) | Sujeto sintético | Media | L | Corregir | F09-27 |
| SEC-015 | El sujeto sintético se da por revertido con una confirmación, sin sonda que lo compruebe; los sujetos sin campaña no bloquean el sello (`seal.py:62`, `synthetic.py:321-352`) | Sujeto sintético | Media | L | Corregir | F09-27 |
| SEC-016 | `verify_seal` acepta un resellado: `campaigns.seal` no tiene trigger, se pueden insertar veredictos en una campaña sellada y vale cualquier asiento `campaign.seal` (`seal.py:88-104`) | Motor y evidencia | Media | L | Corregir | F09-23 |
| SEC-017 | `journal_append` admite cualquier actor y acción a cualquier rol con EXECUTE (incluido `argos_ai`) y no comprueba que el texto sea canónico: claves duplicadas hacen que el hash y el `jsonb` digan cosas distintas (`0001_core.sql:83-107`, `0020_ai_gateway_journal.sql:10`) | Diario | Media | L | Corregir | F09-26 |
| SEC-018 | Revocación sin frescura: un bundle exportado antes de revocar sigue diciendo «no revocada» con su lista de estado antigua (`credential/verify.py:63-80`) | Comprobador público | Media | L | Corregir | F09-20 |
| SEC-019 | El bundle de ontología se descomprime entero en memoria antes de comprobar la firma (`services/ontology/argos_ontology/bundle.py:113-146`) | Ontología | Media | L | Corregir | F09-25 |
| SEC-020 | Ontología sin anti-retroceso (desempata por `loaded_at`) y `load_bundle` no exige la huella de la clave (`bundle.py:175-186`, `store.py:40-43`) | Ontología | Media | L | Corregir | F09-25 |
| SEC-021 | Las funciones denegadas se evaden cualificando con el esquema (`pg_catalog.pg_terminate_backend`) y se admite cualquier función de usuario (en Oracle, transacción autónoma) (`readonly.py:128-131`) | Conectores | Media | C | Corregir | F09-21 |
| SEC-022 | `check_config` devuelve filas en claro y sin tope: un reto `SELECT dni, diagnostico FROM pacientes` trae la tabla a la evidencia (`generic.py:353-355`) | Conectores | Media | L | Corregir | F09-31 |
| SEC-023 | La exploración SQL lanza una consulta por esquema y por tabla con el inspector de SQLAlchemy, sin validación ni diario; tampoco se registran las páginas REST ni la asociación DICOM (`generic.py:312-329`) | Conectores | Media | L | Corregir | F09-22 |
| SEC-024 | Nombres no ASCII u hostiles tumban la clasificación entera o esconden una tabla del inventario (`generic.py:52`, `base.py:75-82`, `graph/model.py`) | Conectores e inventario | Media | L | Corregir | F09-31 |
| SEC-025 | La clasificación asistida acepta sola una rebaja de categoría inducida por un nombre de columna hostil del mismo lote (`classify/assisted.py:~166`, `argos_ai/classify/service.py:75-95`) | IA e inventario | Media | L | Corregir | F09-29 |
| SEC-026 | Permisos de NATS amplios: los servicios pueden actualizar streams y borrar consumidores ajenos; `inventory` puede publicar `argos.campaign.>` (`deploy/dev/nats/nats.conf`) | Bus | Media | C | Corregir | F09-06 |
| SEC-027 | SQL Server con TLS no funciona con `pymssql` (no acepta `encrypt=yes`) y obliga a `allow_insecure` (`generic.py:91-92`) | Conectores | Media | L | Corregir | F09-31 |
| SEC-028 | DICOM sin TLS y pidiendo `PatientID` en la muestra (`connectors/dicom/argos_dicom/connector.py:65-88`) | Conectores | Media | L | Corregir | F09-31 |
| SEC-029 | Un `Idempotency-Key` de varios KB hace fallar el guardado después de ejecutar la mutación y el asiento `api.mutation` nunca se escribe (`services/api/argos_api/core.py:136-157`) | API | Media | L | Corregir | F09-26 |
| SEC-030 | La emisión de credencial y el lanzamiento de campaña no dejan asiento con la persona y la campaña (`credential/issue.py:261`, `routers/credentials.py:73`) | API y diario | Media | L | Corregir | F09-26 |
| SEC-031 | SSRF en webhooks: destino `http(s)` a cualquier host (servicios internos, 169.254.169.254) y el listado de entregas devuelve códigos y errores (`routers/webhooks.py:31`, `webhooks/dispatch.py:183-186`) | API | Media | L | Corregir | F09-30 |
| SEC-032 | Los depuradores no reconocen un DNI pegado a `_` o a letras, ni un IBAN o NUSS con separadores: llegan al modelo en claro (`library/prompts/guardrails.yaml:10-20`) | Gateway de IA | Media | C | Corregir | F09-28 |
| SEC-033 | El asistente no comprueba cifras ni citas contra lo que devolvieron sus herramientas; una cita con `detail` vacío enlaza al primer fragmento (`assistant/agent.py:123-128`, `AssistantView.tsx:51-52`) | Gateway de IA | Media | L | Corregir | F09-28 |
| SEC-034 | El guardarraíl de afirmaciones de veredicto se elude con variantes («cumple el artículo», sin tilde, espacio de ancho cero, inglés) y acepta cualquier veredicto existente como cita (`guardrails/__init__.py:81-106`) | Gateway de IA | Media | C | Corregir | F09-28 |
| SEC-035 | El verificador de cifras de los dictámenes no extrae decimales, rangos ni números pegados: un porcentaje inventado entra en el expediente (`reports/figures.py:233-256`) | Gateway de IA | Media | C | Corregir | F09-28 |
| SEC-036 | Las sondas SHACL leen el grafo vivo y la subsanación mide sobre la instantánea antigua: sin reproducibilidad y hallazgos que no pueden cerrar (`activities.py:266-317`) | Motor de retos | Media | L | Corregir | F09-27 |
| SEC-037 | Un fallo de OPA (token caducado, caída) deja el veredicto `inconclusive` para siempre sin reintento (`activities.py:393-394`, `opa.py:46-47`) | Motor de retos | Baja | L | Corregir | F09-23 |
| SEC-038 | `did_web_url` resuelve `did:web:host%40evil.com` a otro dominio (`credential/did.py:30`) | Evidencia | Baja | C | Corregir | F09-20 |
| SEC-039 | El tamaño de la prueba de Merkle no se contrasta con el `leaf_count` firmado: la posición y el total que informa el comprobador pueden ser falsos (`checks.py:188-189`) | Comprobador público | Baja | C | Corregir | F09-20 |
| SEC-040 | La huella de idempotencia usa la ruta plantilla y se consulta antes de autorizar: una clave reutilizada en otra campaña devuelve la respuesta de la primera (`core.py:113-127`) | API | Baja | L | Corregir | F09-26 |
| SEC-041 | No hay cierre de sesión real y la cookie de refresco es persistente: en un puesto compartido el siguiente entra como el anterior (`console/src/auth/session.ts:100`, `routers/session.py:47-55`) | Consola | Baja | L | Corregir | F09-30 |
| SEC-042 | La aceptación de riesgo admite cualquier fecha (pasada o `9999-12-31`) (`routers/findings.py:39-52`) | API | Baja | L | Corregir | F09-24 |
| SEC-043 | El asistente no tiene límite por persona y la cuota diaria es compartida: una persona la agota para todos (`services/api/argos_api/assistant.py:91`) | Gateway de IA | Baja | L | Corregir | F09-29 |
| SEC-044 | `CoreRoute` valida el JWT de forma síncrona y abre una conexión a la base antes del guardián cuando hay `Idempotency-Key` (`core.py:99-127`) | API | Baja | L | Corregir | F09-26 |
| SEC-045 | Campos de texto sin límite fuera de lo que cubrió la auditoría (`Revocation.reason`, `ReviewDecision.note`, `Exercise.right`, la cabecera `Idempotency-Key`) | API | Baja | L | Corregir | F09-30 |
| SEC-046 | La consola se sirve sin CSP, `frame-ancestors` ni `nosniff` (`app.py:186-206`) | Consola | Baja | L | Corregir | F09-30 |
| SEC-047 | Las herramientas del asistente no tienen `statement_timeout` ni límite de concurrencia (`assistant/tools.py:103-120`) | Gateway de IA | Baja | L | Corregir | F09-29 |
| SEC-048 | `search_regulation` no filtra por origen: un documento del cliente se presentaría como norma citada (`tools.py:123-127`, `rag/pipeline.py:103`) | Gateway de IA | Baja | L | Corregir | F09-29 |
| SEC-049 | `write_verbs` por subcadena: una columna `last_update` hace fallar respuestas y lotes enteros del clasificador (`guardrails.yaml:34-43`) | Gateway de IA | Baja | L | Corregir | F09-28 |
| SEC-050 | Un error de `query_graph` sale del paso como excepción y la API responde 500; `system_kind` nunca funciona (`tools.py:62-120`, `agent.py:96`) | Gateway de IA | Baja | L | Corregir | F09-29 |
| SEC-051 | El rol `argos_ai` lee todo el esquema (semillas del sujeto sintético, respuestas de idempotencia, personas del diario) (`0015_ai_gateway_role.sql:63,69`) | Base de datos | Baja | L | Corregir | F09-04 |
| SEC-052 | El clasificador guarda en `ai_proposals` claves ajenas al lote y duplicadas antes de validar, y contamina la recalibración (`classify/service.py:97-107`) | Gateway de IA | Baja | L | Corregir | F09-29 |
| SEC-053 | El recorrido SMB no cuenta directorios y sigue enlaces simbólicos (`backends/smb.py:33-51`) | Conectores | Baja | L | Corregir | F09-22 |
| SEC-054 | La sonda de privilegios de PostgreSQL falla con nombres con mayúsculas o puntos y deja tablas sin aristas de acceso (`argos_sql/postgres.py:27`) | Conectores | Baja | L | Corregir | F09-31 |
| SEC-055 | Inyección de Markdown/HTML en el informe de inventario con nombres de columna (`catalog/report.py:97-108`) | Inventario | Baja | L | Corregir | F09-31 |
| SEC-056 | `GET /status/{n}` de `evidence-api` firma con Vault en cada petición, sin autenticar: amplificador de coste | Evidencia | Baja | L | Corregir | F09-20 |
| SEC-057 | `vitest` con dos avisos moderados (lectura de ficheros en el servidor de pruebas) | Consola (desarrollo) | Baja | C | **Aceptar** hasta F09-09: es dependencia de desarrollo y no viaja en la imagen; la puerta de vulnerabilidades la tratará con excepción justificada o con la actualización | F09-09 |

**Resumen:** 9 altas, 27 medias y 21 bajas. 56 a corregir, 1 aceptada con fecha (hasta F09-09).

## 3. Observaciones que no son de seguridad

- **El asistente no está conectado en el contenedor:** `argos_ai/api/main.py:22` crea la aplicación sin herramientas, así que `/v1/assistant/ask` responde siempre 503. Se corrige en F09-29.
- **`/auth/refresh` responde 500 ante un refresco rechazado** (`routers/session.py:81`), y `keycloak.py:32` también da 500 si Keycloak devuelve un error que no es JSON. Se corrige en F09-30.
- **Carrera en la idempotencia:** dos peticiones concurrentes con la misma clave ejecutan las dos. Se corrige en F09-26, junto con SEC-040.

## 4. Lo revisado sin hallazgos

- **Validación de JWT:** solo RS256; exige `exp`, `iat`, `iss`, `aud` y `sub`; rechaza ID tokens y refresh tokens.
- **Rutas autenticadas:** las 39 declaran permiso.
- **Sesión:** CSRF y redirección abierta en el callback OIDC, sin fallos.
- **Consola:** estáticos protegidos frente a path traversal; ningún XSS (sin `innerHTML` ni `dangerouslySetInnerHTML`).
- **Webhooks:** plantillas ITSM sin inyección; firma HMAC con marca de tiempo y comparación en tiempo constante.
- **Inventario:** Cypher parametrizado en toda la ingesta; etiquetas en lista blanca; límites de GraphQL.
- **Conectores:** REST y FHIR sin redirecciones y con paginación del mismo origen; LDAP sin referrals.
- **Diario:** huecos de `seq` y génesis cubiertos.
- **Evidencia:** separación hoja/nodo en el Merkle; canonización de artefactos y expediente; TSA con nonce e imprint.
- **Motor de retos:** doble control frente a mayúsculas o tokens repetidos; aprobaciones ligadas a su campaña; YAML seguro; cierre de hallazgos solo por reejecución.

## 5. Efecto sobre el modelo de amenazas

Hay mitigaciones que el modelo daba por implementadas y tienen huecos: M-01, M-03, M-05, M-06, M-12, M-13, M-14 y M-28. En la versión 1.2 del modelo pasan a «en desarrollo» con su tarea de corrección, y vuelven a «implementada» cuando esa tarea se cierre.

## 6. Seguimiento de las correcciones

Cada fila se añade cuando la tarea que corrige el hallazgo se cierra, con el commit donde se ve la corrección y su test.

| Hallazgo | Estado | Tarea | Commit | Fecha |
|---|---|---|---|---|
| SEC-001, SEC-002, SEC-003, SEC-018, SEC-038, SEC-039, SEC-056 | Corregido | F09-20 | `90790cf` | 2026-09-23 |
| SEC-005, SEC-006, SEC-021 | Corregido | F09-21 | `031b9bc` | 2026-09-23 |
| SEC-004, SEC-023, SEC-053 | Corregido | F09-22 | `4ed4faf` | 2026-09-23 |
| SEC-007, SEC-009, SEC-010, SEC-012, SEC-013, SEC-016, SEC-037 | Corregido | F09-23 | `4d9b209` | 2026-09-23 |
| SEC-008, SEC-042 | Corregido | F09-24 | `03c53c6` | 2026-09-23 |
| SEC-011, SEC-019, SEC-020 | Corregido | F09-25 | `216d7a0` | 2026-09-23 |
| SEC-014, SEC-015, SEC-036 | Corregido | F09-27 | `63bc69c` | 2026-09-23 |

## 7. Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-09-23 | Primera revisión (F09-02) |
| 1.1 | 2026-09-23 | Corregidos SEC-001, 002, 003, 018, 038, 039 y 056 (F09-20) |
| 1.2 | 2026-09-23 | Corregidos SEC-005, 006 y 021 (F09-21) |
| 1.3 | 2026-09-23 | Corregidos SEC-004, 023 y 053 (F09-22) |
| 1.4 | 2026-09-23 | Corregidos SEC-007, 009, 010, 012, 013, 016 y 037 (F09-23) |
| 1.5 | 2026-09-23 | Corregidos SEC-008 y 042 (F09-24) |
| 1.6 | 2026-09-23 | Corregidos SEC-011, 019 y 020 (F09-25) |
| 1.7 | 2026-09-23 | Corregidos SEC-014, 015 y 036 (F09-27) |
