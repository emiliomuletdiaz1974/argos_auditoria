# Revisión de calidad de las Fases 01 a 10

**Versión:** 1.3 · **Fecha:** 2026-09-28 · **Base:** `main` en `d74ba47` (tag `fase-10`) · **Confidencialidad:** `internal`
**Tarea:** QA-01 · **Relacionado:** [revisión de seguridad de F1–F8](../seguridad/revision-f01-f08.md), [modelo de amenazas](../seguridad/modelo-amenazas.md)

Revisamos todo lo construido en `argos/` buscando errores de funcionamiento y casos borde, no estilo. Tratamos los hallazgos como los de un cliente, igual que en F09-02: cada uno queda **registrado** aquí, se **corrige** en una tarea `QA-2N` con un test que lo reproduce primero, y la corrección queda **evidenciada** en el commit y en este registro.

## 1. Cómo se hizo

| Pasada | Qué | Resultado |
|---|---|---|
| Lectura dirigida en paralelo | Seis bloques: A cimientos (`libs/*`, migraciones); B conectores; C inventario y ontología; D motor de retos y evidencia; E IA, API y consola; F plataforma y operación (Fases 09 y 10) | 89 hallazgos |
| Reproducción | Funciones puras con entradas límite: validadores, validador SQL, ventana de sondeo, analizadores de sala, evaluador y muestreo, Merkle, comprobador, guardarraíles, clasificador, compilador | 25 confirmados ejecutando el código |
| Comprobación en el código | Los hallazgos graves que dependen de la base, NATS o Temporal | 24 confirmados leyendo el código |

**Fuera de este registro:**
- `argos-web`, por decisión del usuario del 2026-09-28.
- Lo ya anotado en pendientes y los hallazgos SEC-001…060, salvo cuando la corrección no funciona: entonces se registra aquí y se reabre allí (sección 5).

**Criterio de severidad:**
- **Alta:** datos, veredicto o evidencia incorrectos; una promesa del producto rota (solo lectura, integridad, firma); pérdida de datos o una caída que no se recupera sola.
- **Media:** funcionalidad errónea en un caso borde plausible, o un fallo que se ve y se recupera.
- **Baja:** caso raro, robustez o diagnóstico.

**Verificación:**
- **R** (reproducido): ejecutado en esta revisión, con la salida que lo muestra.
- **L** (leído): confirmado leyendo el código en esta revisión.
- **S** (señalado): identificado por el revisor del bloque con archivo y línea, sin confirmar todavía. Se confirma, o se descarta, con el test que falla al empezar su tarea.

## 2. Hallazgos

### A · Cimientos

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-001 | El bus descarta en silencio un evento tras 5 entregas fallidas: no hay cola de fallidos ni aviso, y el log dice «will be redelivered» también en la última (`libs/events/argos_events/__init__.py:178-195`). Un corte de la base de pocos minutos deja inventarios incompletos o campañas selladas sin expediente | Alta | L | QA-25 |
| QA-002 | Registro de seguridad: el resumen de una ráfaga solo se escribe si llega otro evento con la misma clave pasada la ventana, o con `flush()`, que nadie llama. Una ráfaga corta queda en 10 eventos y la alerta de fuerza bruta no salta; `_windows` crece sin límite (`libs/common/argos_common/security_log.py:83-136`) | Media | L | QA-33 |
| QA-003 | `cert-issuer`: el fallo de un servicio corta la renovación de todos los que van detrás en la lista (`libs/tls/argos_tls/issuer.py:143-157`) | Media | S | QA-33 |
| QA-004 | La conexión a NATS reconecta con el `SSLContext` del arranque: a los 30 días presenta un certificado caducado (`libs/events/argos_events/__init__.py:95`) | Media | S | QA-25 |
| QA-005 | `Bus.publish` no envía `Nats-Msg-Id` (un reintento publica otro evento con otro id) y escribe el asiento del diario antes de serializar (`libs/events/argos_events/__init__.py:151-166`) | Media | S | QA-25 |
| QA-006 | El límite de campañas en paralelo se supera con lanzamientos seguidos: una campaña recién lanzada sigue en `planned` o en `pinned` sin petición de compuerta y no cuenta; medir y comprobar va sin bloqueo (`libs/common/argos_common/capacity.py:38-40`, `services/api/argos_api/routers/campaigns.py:118-119`). Lo introdujo la corrección de F10-99 | Media | L | QA-32 |
| QA-007 | El formateador JSON descarta todo `extra` que no sea `journal_seq`, `trace_id` o `campaign_id`: 14 llamadas pierden su contexto (`libs/common/argos_common/logs.py:43`) | Media | L | QA-33 |
| QA-008 | `build_manifest` firma un manifiesto sin SBOM si la carpeta no existe; `_image_name` devuelve el registro con puerto (`registry.local:5000/argos-api@…` → `registry.local`) (`libs/common/argos_common/release.py:24,44`) | Media | R | QA-34 |
| QA-009 | JWT sin margen de reloj: un token con `iat` un segundo en el futuro se rechaza; `realm_access` como lista da 500 y `roles` como cadena da un conjunto de caracteres (`libs/auth/argos_auth/__init__.py:57`) | Baja | S | QA-34 |
| QA-010 | La configuración de producción no exige `sslmode=verify-full` hacia PostgreSQL, y detecta «base local» por subcadena (`libs/common/argos_common/config.py:132,142-151`) | Baja | S | QA-34 |
| QA-011 | `cert-issuer`: un corte entre la escritura de la clave y la del certificado los deja desparejados y no se corrige solo; el servicio no arranca (`libs/tls/argos_tls/issuer.py:153-155`) | Baja | S | QA-33 |
| QA-012 | `journal_append` y `security.append` toman la hora antes del cerrojo: el orden por `at` puede no coincidir con el orden por `seq` (`0034_journal_grants.sql:77,100`, `0036_security_log.sql:49,64`) | Baja | S | QA-34 |
| QA-013 | `security_metrics` recorre la cadena entera del registro de seguridad en cada *scrape*: crecerá hasta pasar el timeout y la métrica desaparecerá en vez de valer 0 (`services/api/argos_api/security_events.py:70`) | Baja | S | QA-22 |
| QA-014 | El migrador no avisa de versiones aplicadas que faltan en el directorio (código más viejo que el esquema), y el `rollback()` del `finally` tapa la excepción original (`libs/common/argos_common/migrations.py:253-291`) | Baja | S | QA-34 |

### B · Conectores

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-015 | `check_config` acepta tablas con prefijo de catálogo en cualquier esquema (`public.pg_pacientes`; en Oracle `clinica.all_pacientes`), y qué columnas salen en claro lo decide el alias: `SELECT dni AS value …` devuelve DNI sin digest (`connectors/sdk/argos_connector/config_sources.py:70-77,116`). Variante de SEC-022 | Alta | R | QA-23 |
| QA-016 | SMB cuenta los directorios contra el tope de recorrido y `capped` solo mira ficheros: un recuento incompleto sale como completo (`connectors/files/argos_files/backends/smb.py:40-46`, `connector.py:124,144`) | Alta | L | QA-23 |
| QA-017 | La tasa de aceptación de los validadores cuenta `''` y los espacios como valores inválidos (`['12345678Z','','  ']` → 0,33), y rechaza DNI con guion o de 7 dígitos: una columna de DNI real no llega al 0,9 y no se clasifica. En sentido contrario, acepta dígitos de ancho completo (`connectors/sdk/argos_connector/validators.py:13,131`) | Alta | R | QA-24 |
| QA-018 | Una ventana de sondeo nocturna (`22:00`→`06:00`) nunca está abierta, y `parse_windows` no la rechaza: todas las sondas se bloquean sin avisar (`connectors/sdk/argos_connector/budget.py:71,158`) | Media | R | QA-24 |
| QA-019 | Un literal sin cerrar (`SELECT 'abc`) lanza `TokenError` y no `ReadOnlyViolationError`: el rechazo no queda en el diario, y el lint y el generador de retos se caen (`connectors/sdk/argos_connector/readonly.py:231`, `config_sources.py:84`) | Media | R | QA-24 |
| QA-020 | SQL Server con pyodbc (el único camino con TLS verificado) no tiene timeout de consulta, solo de login (`connectors/sql/argos_sql/generic.py:155-156,250`) | Media | S | QA-24 |
| QA-021 | S3: `normalise_prefix('pacientes/')` da `pacientes`, así que también se cuentan `pacientes_2019/…`; un marcador de carpeta (`docs/`) hace fallar la muestra (`connectors/files/argos_files/backends/s3.py:34,44`) | Media | R | QA-23 |
| QA-022 | REST: `route_for` revisa también la *query*; un cursor con `%2F` se toma por ataque y aborta el recuento, y en `half_open` deja el circuito bloqueado todo el enfriamiento (`connectors/rest/argos_rest/connector.py:141-146`) | Media | L | QA-24 |
| QA-023 | El validador y el motor leen distinto la barra invertida con `NO_BACKSLASH_ESCAPES` (MySQL) o `standard_conforming_strings=off` (PostgreSQL): `SELECT '\'; DELETE …` pasa. La sesión de solo lectura lo sigue parando (`readonly.py:230`) | Baja | R | QA-24 |
| QA-024 | Oracle: la exploración ignora `params.schemas` y mete columnas de vistas (`connectors/sql/argos_sql/oracle.py`) | Media | S | QA-23 |
| QA-025 | `LocalBackend`: un enlace roto o un fichero borrado durante el recorrido tumba la sonda; los directorios sin permiso desaparecen del recuento sin marca (`connectors/files/argos_files/backends/local.py:26,30`) | Baja | S | QA-23 |
| QA-026 | LDAP: `count` y `scan_schema` sin tope de entradas y con un solo permiso de presupuesto para todas las páginas. Variante de SEC-023 (`connectors/ldap/argos_ldap/connector.py`) | Baja | S | QA-23 |
| QA-027 | Una `k` negativa en la muestra: `LIMIT -1` (sin límite en SQLite), `items[:-1]` en REST, `_count=-1` en FHIR | Baja | S | QA-23 |
| QA-028 | DICOM: el patrón de fecha acepta `-` y 16 dígitos sin guion; `$` admite un salto de línea final; `capped` es verdadero con exactamente `max_studies` (`connectors/dicom/argos_dicom/connector.py:27-28,157,168`) | Baja | S | QA-23 |

### C · Inventario y ontología

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-029 | Un `table_found` reentregado después del `scan_completed` produce un delta «desaparecida» falso; un `access_found` que llega antes que su tabla se pierde sin error (`services/inventory/argos_inventory/scheduler/activities.py:136`, `versioning/deltas.py`) | Alta | S | QA-26 |
| QA-030 | `compute_deltas` no es atómico: el marcado `missing` se confirma antes del asiento y del evento; un reintento pierde las desapariciones y duplica el asiento (`versioning/deltas.py:117-162`) | Alta | L | QA-26 |
| QA-031 | Una pasada que se queda en `running` (el worker cae durante `run_scan`) saca al sistema del planificador para siempre: nada limpia las pasadas colgadas (`scheduler/activities.py:37`, `scheduler/policy.py:53`) | Alta | L | QA-26 |
| QA-032 | Los permisos revocados no desaparecen nunca: `CAN_ACCESS` e `Identity` solo se fusionan, no se marcan `missing` ni generan delta (`ingest/handlers.py`, `versioning/deltas.py`) | Media | L | QA-26 |
| QA-033 | Un tratamiento que se quita del CSV del RAT no se elimina, contra lo que dice el docstring del módulo (`catalog/treatments.py`) | Media | S | QA-26 |
| QA-034 | El diccionario no reconoce nombres con tilde o ñ (`teléfono` → `tel`, `fono`), plurales (`emails`) ni siglas pegadas (`DNIPaciente`) (`classify/dictionary.py:137-143`) | Media | R | QA-27 |
| QA-035 | `location_data` no tiene clase de activo: ninguna obligación selecciona una tabla con domicilios o coordenadas; tampoco hay clase para `technical_credential` (`library/ontology/asset-classes/base.ttl`) | Media | L | QA-27 |
| QA-036 | `library_fingerprint` ordena objetos `Path`: el orden, y con él el SHA-256 que va en el sello de la campaña, cambia entre Windows y Linux (`services/ontology/argos_ontology/library_hash.py:12-17`) | Media | R | QA-27 |
| QA-037 | ODRL ignora el operador: `purpose neq marketing` da `allowed_purposes: [marketing]` y `elapsedTime gteq P5Y` da `max_days`; las cláusulas no traducidas no se marcan `unsupported` (`services/ontology/argos_ontology/odrl.py:93-115,159-180`). Latente: `to_challenges` aún no se llama en producción | Media | L | QA-27 |
| QA-038 | El compilador acepta fecha con hora en `vigente_desde` y genera un `xsd:date` inválido; `in_force` lanza `TypeError` con él, y una fecha mal formada hace la obligación siempre vigente (`editorial/compiler.py:80,121`, `resolver.py:133-143`) | Media | R | QA-27 |
| QA-039 | Un `table_found` repetido pisa `est_rows_prev` y borra la detección de crecimiento anómalo; un evento viejo reentregado hace retroceder `last_seen` (`ingest/handlers.py:274`) | Media | S | QA-26 |
| QA-040 | Las instantáneas «inmutables» admiten INSERT, y `verify_snapshot` no se llama al usarlas (`0005_inventory_versioning.sql:41-52`, `versioning/snapshots.py:139`) | Media | S | QA-26 |
| QA-041 | Clasificación asistida: el rechazo del DPO no se recuerda, y aceptar no fija la categoría que la persona vio. Latente (`classify/assisted.py`) | Baja | S | QA-27 |
| QA-042 | Flujos: el mejor candidato depende del orden en que AGE devuelve las filas; `split('|')` se rompe con un nombre de columna con `|` (`flows/detect.py`) | Baja | S | QA-27 |
| QA-043 | Si la sonda de validación en origen falla, la columna ya no se vuelve a validar (`classify/deterministic.py`) | Baja | S | QA-26 |

### D · Motor de retos y evidencia

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-044 | La severidad de un hallazgo sube en cada avistamiento desde el tercero, no una sola vez: `low, low, medium, high, critical` en cinco campañas, y también en reintentos y subsanaciones (`services/challenge-engine/argos_challenges/findings.py:85-131`) | Alta | R | QA-28 |
| QA-045 | Modo aislado: `process_queue` reescribe el nonce de todo lo encolado antes de llamar al transporte; cualquier intento en línea invalida las peticiones ya exportadas por la esclusa (`services/evidence/argos_evidence/tsa.py:132-141,200-216`) | Alta | L | QA-29 |
| QA-046 | `plan_sampling` sigue sin usarse: un reto de umbral `count` con `muestreo` llega al evaluador sin `population` y falla con `KeyError`. SEC-009 no quedó cerrado del todo (`compiler.py:149`, `evaluator.py:135`) | Media | R | QA-28 |
| QA-047 | Un umbral o un valor observado con decimales hace fallar el hash del veredicto (`floating point number not allowed`) y la unidad agota sus reintentos (`evaluator.py:66-71,117-122`) | Media | R | QA-28 |
| QA-048 | El sello no se puede reintentar: si falla el anuncio tras sellar, el reintento lanza «already sealed», el workflow falla y el evento nunca sale, así que no hay expediente (`activities.py`, `seal.py:106-107`) | Media | L | QA-28 |
| QA-049 | `prepare_campaign` no es idempotente después de fijar la campaña: cada reintento toma otra instantánea y falla; la campaña queda `pinned` con instantáneas huérfanas (`activities.py:189-243`) | Media | S | QA-28 |
| QA-050 | Una campaña sellada sin veredictos hace fallar el workflow de evidencia (`a campaign without artifacts has no Merkle root`): ni expediente ni credencial (`services/evidence/argos_evidence/activities.py:108-119`) | Media | R | QA-29 |
| QA-051 | Si falla el anuncio de un hallazgo, el reintento no lo anuncia (`created` ya es falso) y escribe un `finding.recur` de más (`activities.py:621-628`) | Baja | S | QA-28 |
| QA-052 | El comprobador público devuelve 500 con tipos inesperados (`artifacts: 5`, `evidence_chain` o `merkle` como cadena) (`services/verifier/argos_verifier/checks.py:225-229`) | Baja | R | QA-29 |
| QA-053 | Con el operador `<`, el tamaño de muestra que se propone no demuestra el umbral (3838 sin fallos → `not_demonstrated`) (`evaluator.py:158-164`) | Baja | R | QA-28 |
| QA-054 | Con muestreo, los operadores `>=` y `>` invierten la lógica. Hoy inalcanzable por QA-046 (`evaluator.py:149-155`) | Baja | R | QA-28 |
| QA-055 | Una prueba de inclusión de Merkle verifica también con otro tamaño de árbol (hoja 0 de 5 con tamaño 6); el test elige justo la hoja que falla. El comprobador está protegido por el `leaf_count` firmado; el script autónomo no (`services/evidence/argos_evidence/merkle.py:98-115`) | Baja | R | QA-29 |
| QA-056 | La biblioteca se vacía si una carpeta padre del repositorio se llama `archive` o `schema`: se mira `path.parts` de la ruta absoluta (`library/catalog.py:73,132`, `dsl.py:144`) | Baja | L | QA-28 |

### E · IA, API y consola

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-057 | Idempotencia: una respuesta 2xx que no es JSON (el paquete de soporte) hace fallar `complete` después del efecto; el cliente recibe 500 y la clave queda «en curso» para siempre (`services/api/argos_api/core.py:100-105,197-231`) | Alta | L | QA-31 |
| QA-058 | El guardarraíl de veredicto no citado se esquiva con frases corrientes: «Concluyo que cumple», «plenamente conforme», inglés, `c` cirílica, «no se aprecia ningún incumplimiento», «se ajusta al RGPD». Variante de SEC-034 (`library/prompts/guardrails.yaml`, `argos_ai/guardrails/__init__.py:111-125`) | Alta | R | QA-30 |
| QA-059 | El guardarraíl de escritura se esquiva con SQL válido: `UPDATE t p SET …`, `DELETE t WHERE …`, `MERGE`, `GRANT`, `CREATE TABLE … AS SELECT`, `rm -rf` | Alta | R | QA-30 |
| QA-060 | `/internal/alertmanager`: 500 con cuerpo malformado (sin `fingerprint`, `alerts` como cadena, fecha inválida); la regex de runbook admite `\n` final y dígitos Unicode, que el CHECK de PostgreSQL rechaza y hacen perder el lote entero (`routers/operations.py:70-84`, `operations.py:49,118-131`) | Media | L | QA-32 |
| QA-061 | `POST /systems`: medir e insertar van sin bloqueo; dos altas simultáneas superan la talla. Relanzar una campaña en el límite da 409 de capacidad en vez de error de estado (`routers/systems.py:84-87`) | Media | S | QA-32 |
| QA-062 | Consola: el visor de runbooks entra en bucle infinito con una línea `##### x`, `#etiqueta` o `#`, que no es título ni párrafo (`console/src/views/operations/Markdown.tsx:44-73`) | Media | L | QA-32 |
| QA-063 | Los errores reales de Temporal llegan como 500: una campaña no lanzada, un segundo `verify` en curso o relanzar mientras corre. Los tests usan un runner en memoria que lanza otra excepción (`services/api/argos_api/main.py:62-98`) | Media | S | QA-31 |
| QA-064 | La paginación de hallazgos ordena por `occurrences`, que cambia entre páginas: se pierden o repiten elementos; `lpad(…, 6)` trunca (`argos_challenges/findings.py:262-273`) | Media | S | QA-31 |
| QA-065 | Un cursor decodificable con fecha inválida acaba en `DataError` y 503 «store not available» en vez de 400 (`services/api/argos_api/paging.py:36-46`) | Baja | S | QA-31 |
| QA-066 | Una alerta que vuelve a saltar conserva el `starts_at` antiguo; un `firing` tardío tras el `resolved` deja una alerta fantasma (`operations.py:177-189`) | Baja | S | QA-32 |
| QA-067 | La nota del DPO al revisar una columna se valida y se descarta: no llega ni al diario ni a la cola (`routers/inventory.py:30-40,115-122`) | Media | L | QA-31 |
| QA-068 | RAG: no se contrasta que la cita `n` corresponda a su `reference`, y lo permitido solo se mira por `reference`. Resto de SEC-048 (`argos_ai/rag/pipeline.py:84-93,133-136`) | Baja | S | QA-30 |
| QA-069 | Consola: `fragmentOf` muestra el texto de un artículo bajo una cita de estado (`console/src/views/assistant/AssistantView.tsx:51-58`) | Baja | S | QA-30 |
| QA-070 | Asistente: una negativa no pasa el control de cifras; un rechazo por escritura (422) llega como 502 «citaba lo que no consultó»; `campaign_id` se acepta y se ignora | Baja | S | QA-30 |
| QA-071 | El depurador de entrada no reconoce DNI con guiones (`12-345-678-Z`), con carácter de ancho cero ni IBAN con puntos (`guardrails.yaml`, `scrub_input`) | Baja | R | QA-30 |

### F · Plataforma y operación

| ID | Hallazgo | Sev. | Verif. | Tarea |
|---|---|---|---|---|
| QA-072 | El instalador captura y descarta la salida de `seal-disk.sh`: la clave de recuperación LUKS, que se imprime una sola vez, nunca llega al operador; cada reintento añade otra clave que tampoco se ve (`services/installer/argos_installer/__init__.py:122-126,334`, `platform/image/seal-disk.sh:23-31`) | Alta | L | QA-21 |
| QA-073 | El actualizador carga todos los `images/*.tar` del paquete aunque el manifiesto no los firme, y no comprueba los `RepoTags`: una imagen sin firmar puede reetiquetar la de otro servicio. La esclusa usa la misma verificación (`services/updater/argos_updater/__init__.py:127-186,248-251`) | Alta | L | QA-20 |
| QA-074 | Un despliegue que falla dentro de `deploy()` no se deshace (el paso no llegó a `done`) y se borra el plan de vuelta atrás: versiones mezcladas sin que conste (`updater/__init__.py:295-330`) | Alta | L | QA-20 |
| QA-075 | Sala: una fuente con estado `na` o de fallo cuenta como presente, y una lectura de potencia `na` se ignora: «fuente redundante» y «potencia» aptas con una sola fuente (`installer/site_check.py:103-112`) | Alta | R | QA-21 |
| QA-076 | Sala: los sensores de 12 V y 3,3 V entran en la comprobación de tensión de red: «no apto» en cualquier servidor real (`site_check.py:114-115`) | Media | R | QA-21 |
| QA-077 | Sala: un ping con 90 % de pérdida da latencia apta; la salida de busybox se lee como «no responde» (`site_check.py`, `parse_ping`) | Media | R | QA-21 |
| QA-078 | Salud: `publish()` renueva la fecha de todos los hechos cada 30 s aunque la comprobación que los produce esté colgada; la regla de frescura de 15 minutos no lo detecta (`services/health/argos_health/app.py:95-97`, `measures.py:347-356`) | Media | S | QA-22 |
| QA-079 | Salud: si falla una consulta de dominio desaparecen todas las métricas de dominio y ninguna alerta salta (no hay reglas `absent()`); `certs_expiring_7d = -1` y un volumen sin ruta tampoco alertan (`monitor.py:129-137`, `measures.py:209-256`) | Media | S | QA-22 |
| QA-080 | Conmutación de la M: un error de autenticación o de red se toma como «primario caído» y se promueve la réplica; `coalesce(…, 0)` da lag 0 a una réplica que nunca reprodujo; no se mira el resultado de `pg_promote`; `rejoin` borra el volumen sin `--confirm` (`platform/ha/size-m/failover.py:32-50`, `rejoin.py`) | Media | L | QA-35 |
| QA-081 | Instalador: la verificación del administrador busca `"username": "x"`, pero `kcadm.sh` imprime `"username" : "x"`; y no comprueba el rol ni las acciones obligadas (`installer/__init__.py:233-240`) | Media | S | QA-21 |
| QA-082 | `argos-health` queda fuera de la release firmada, del SBOM, de la puerta de vulnerabilidades y del actualizador (`Makefile`, `tools/sbom.py`, `services/updater/argos_updater/cli.py`) | Media | L | QA-34 |
| QA-083 | Al reanudar, el informe firmado del instalador solo lleva los pasos de la última ejecución (se pierde la sala, evidencia P-26); `state.json` no está ligado a la huella de la configuración (`installer/__init__.py:323-365`) | Media | L | QA-21 |
| QA-084 | `argos-update watch` muere con cualquier error que no sea `UpdateRejectedError`, y la petición ya está borrada (`services/updater/argos_updater/cli.py:108-117`) | Baja | S | QA-20 |
| QA-085 | La esclusa descomprime un `argos-update-*.tar` comprimido antes de verificar la firma, sin límite de tamaño descomprimido (`services/airgap/argos_airgap/importers.py:40-41`) | Baja | S | QA-20 |
| QA-086 | Backup: los recuentos «del volcado» se toman después del volcado (falsa alerta crítica); la prueba de restauración solo detecta tablas a cero (`platform/backup/backup.py:83-87`, `restore_test.py:134-146`) | Baja | S | QA-35 |
| QA-087 | Sala: `ethtool` con `Speed: Unknown!` y el enlace activo se informa como «enlace caído» (`site_check.py`, `parse_ethtool`) | Baja | R | QA-21 |
| QA-088 | Salud: los certificados caducados de nombres retirados cuentan para siempre en `certs_expiring_7d` mientras Vault no haga *tidy* | Baja | S | QA-22 |
| QA-089 | `vuln_gate` falla cerrado si grype da una fecha con hora | Baja | S | QA-34 |

## 3. Resumen

| Bloque | Alta | Media | Baja | Total | R | L | S |
|---|---|---|---|---|---|---|---|
| A · cimientos | 1 | 7 | 6 | 14 | 1 | 4 | 9 |
| B · conectores | 3 | 6 | 5 | 14 | 6 | 2 | 6 |
| C · inventario y ontología | 3 | 9 | 3 | 15 | 3 | 5 | 7 |
| D · retos y evidencia | 2 | 5 | 6 | 13 | 8 | 3 | 2 |
| E · IA, API y consola | 3 | 6 | 6 | 15 | 3 | 4 | 8 |
| F · plataforma y operación | 4 | 8 | 6 | 18 | 4 | 6 | 8 |
| **Total** | **16** | **41** | **32** | **89** | **25** | **24** | **40** |

Lo que más pesa:
- **Promesas rotas del producto:** una imagen sin firmar entra por el actualizador (QA-073), la clave de recuperación del disco se pierde (QA-072), y la sala da «apta» con una sola fuente (QA-075).
- **Cosas que fallan en silencio:** eventos descartados (QA-001), deltas y exploraciones que se pierden (QA-029…031) y métricas que desaparecen sin alerta (QA-079).
- **Guardarraíles de IA** que se esquivan con frases corrientes (QA-058, QA-059).
- **La Fase 10, que nadie había revisado:** 20 hallazgos, cuatro de severidad alta.

## 4. Lo revisado sin hallazgos

- **Diario:** la canonización de Python y la de PostgreSQL coinciden (orden de claves, escapes, enteros grandes, no ASCII); la serialización de escritores con el cerrojo es correcta.
- **Validador de solo lectura:** bloquea CTE con DML, `SELECT INTO`, `FOR UPDATE`/`FOR SHARE`, pistas de bloqueo, dblink, OPENROWSET, funciones denegadas cualificadas y multi-sentencia (unos 50 casos límite).
- **Evidencia:** Merkle distingue hoja y nodo; ninguna prueba verifica en otro índice (barrido de 1 a 129 hojas); la firma Ed25519, el escape del PDF y la descompresión acotada de la lista de estado están bien.
- **Ontología:** el viaje de literales RDF por N3, la verificación del bundle (manifiesto primero, rutas con `..`, límites), el selector y la paginación de GraphQL, y `natural_key`.
- **API de la Fase 10:** `/operations/runbooks/{id}` sin *path traversal*; la matriz de autorización coincide con los routers; los permisos de la migración 0044 son correctos; la cuota de IA se descuenta aunque la llamada falle.
- **Operación:** `drill.py` lee bien los 12 runbooks; `cis_gate`, `sbom` y `release` sin más hallazgos que los listados.

**Sin revisar a fondo** (queda para una segunda pasada): `services/support` (paquete de diagnóstico), exportadores de la esclusa, `harden.sh`, `platform/k8s`, la configuración Patroni de la L, webhooks, credenciales y evidencia en la API, clasificación calibrada y generación de retos, dictámenes, embeddings, y las vistas de inventario, hallazgos y evidencia de la consola.

## 5. Efecto sobre registros anteriores

- **Revisión de seguridad de F1–F8:** SEC-009 (muestreo) y SEC-034 (guardarraíles de salida) no quedaron cerrados del todo: se reabren con QA-046, QA-058 y QA-059. SEC-022 y SEC-023 tienen variantes nuevas (QA-015, QA-026), y SEC-048 un resto (QA-068).
- **Modelo de amenazas:** vuelven a «en desarrollo» M-08 (guardarraíles, QA-30) y M-27 (actualizador firmado, QA-20); se añade la minimización de `check_config` a la tarea QA-23.
- **Informe de cierre de la Fase 10:** su prueba de aceptación pasa, pero no cubría ninguno de estos casos. El tag `fase-10` no se toca: estas correcciones son tareas nuevas.

## 6. Seguimiento de las correcciones

Cada fila se añade cuando la tarea que corrige el hallazgo se cierra, con el commit donde se ve la corrección y su test. Un hallazgo `S` que su test no reproduce se cierra como «no reproducido», con el motivo.

| Hallazgo | Estado | Tarea | Commit | Fecha |
|---|---|---|---|---|
| QA-073, QA-074, QA-084, QA-085 | Corregido (QA-084 y QA-085, que eran `S`, reproducidos por su test antes de corregir) | QA-20 | `8942fd1` | 2026-09-28 |
| QA-072, QA-075, QA-076, QA-077, QA-081, QA-083, QA-087 | Corregido (QA-081, que era `S`, lo reprodujo el propio test del instalador con la salida real de `kcadm.sh`) | QA-21 | `6c030a9` | 2026-09-28 |
| QA-013, QA-078, QA-079, QA-088 | Corregido (los cuatro eran `S`; sus tests los reprodujeron antes de corregir) | QA-22 | `081851e` | 2026-09-28 |

## 7. Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-09-28 | Primera versión (QA-01): 89 hallazgos en seis bloques |
| 1.1 | 2026-09-28 | Corregidos QA-073, 074, 084 y 085 (QA-20) |
| 1.2 | 2026-09-28 | Corregidos QA-072, 075, 076, 077, 081, 083 y 087 (QA-21) |
| 1.3 | 2026-09-28 | Corregidos QA-013, 078, 079 y 088 (QA-22) |
