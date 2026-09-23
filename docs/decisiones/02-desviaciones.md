# 02 · Desviaciones respecto a los documentos de fase

**Confidencialidad:** `internal` · [← índice](README.md)

Una nota de desviación explica por qué no construimos algo tal como lo describe su documento de fase. Casi todas responden a una de cuatro causas:

- **código de referencia que no funciona** con las versiones reales (AGE 1.5.0, Python 3.12, psycopg, ldap3…);
- **infraestructura que el documento da por existente** y no existe: `argos_db`, `uuid.uuid7`, clientes sin definir, cosign, GitLab o k3s;
- **seguridad**: inyección, filtrado de datos o escrituras encubiertas;
- **ADR-0005**: nombres en castellano que pasan al inglés.

Cada ficha resume en una línea lo que pedía el documento, lo que hicimos en su lugar, el motivo y lo que comprobamos antes. Si no quedó comprobación escrita, se dice así. La nota completa está en `docs/desviaciones/`.

> **Sobre `journal_append`.** Varias notas dicen que el documento de fase llama a `journal_append` «en SQL». La función `argos.journal_append` sí existe (ADR-0002), pero con otra firma, y no se llama a mano. Todo el código escribe con `PostgresJournal`. El 2026-09-23 se corrigió esa frase en las notas donde parecía decir que la función no existía.

## Fase 01 · Cimientos

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-002-003 | Imagen Packer y k3s en la F1 | Docker Compose con los mismos servicios; Keycloak publicado en `127.0.0.1:8180` | No hay hardware; un `httpd` local ya ocupaba el 8080 y falseaba un test | El puerto 8080 estaba ocupado en la máquina de trabajo | Aprobada vía ADR-0001 |
| ARG-005 | Diario con `FOR UPDATE`, IDENTITY y hash sobre `::text` | La especificación de ADR-0002 y el migrador en `argos_common.migrations` | Bifurcación concurrente, huecos, hash ambiguo; el migrador fallaba en la primera ejecución | Análisis de defectos (ver ADR-0002) | Aprobada vía ADR-0002 |
| ARG-010 | GitLab CI y cosign | GitHub Actions; manifiesto firmado con Ed25519 en Vault; imágenes fijadas por `Id`; Makefile válido en cmd | El proyecto vive en GitHub; no hay registro de imágenes; `$(shell cat)` y `bash` fallan en Windows | `bash` resolvía al lanzador de WSL | Aprobada vía ADR-0003 |
| ARG-066 | `verify_chain` con otra fórmula | `PostgresJournal.verify` de ADR-0002; ARG-066 aporta el anclaje y el informe | Con dos fórmulas, todo el diario saldría corrupto | — | Aprobada vía ADR-0002 |

## Fase 02 · Conectores de solo lectura

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-011 | Solo lectura comprobando el primer verbo | Árbol sintáctico de sqlglot: una sola sentencia, sin nodos de escritura ni funciones con efectos; `execute()` final de verdad; HMAC por sistema | CTE con DELETE, `;DROP`, `SELECT INTO`, `FOR UPDATE` o `nextval()` pasan el filtro por verbo; `str(e)` filtra datos de filas | **sqlglot 30.18 rechaza los 27 casos en cinco dialectos** (2026-09-14) | Aprobada (F02-R) |
| ARG-012 | Diario de consultas con un pool global y `UPDATE` libre | Diario y `connector_queries` en la misma transacción; cierre único por trigger; los rechazos quedan registrados | Registrar después no vale; cierres dobles o silenciosos; rechazos invisibles | — | Aprobada (F02-R) |
| ARG-013 | Semiabierto sin límite; evento solo en un comentario | Una sola sonda en semiabierto; reloj inyectable; evento `campaign.circuit_open.v1`; tope de filas por sonda | ARG-043 depende del evento; P-05 exige limitar el volumen | — | Aprobada (F02-R) |
| ARG-014-016 | SQL con f-strings; `ALTER SESSION SET READ ONLY` en Oracle | SQLAlchemy Core compilado por dialecto y validado con sqlglot; ajustes de sesión en `connect`; `SET TRANSACTION READ ONLY` en Oracle | Inyección; esa sentencia no existe en Oracle; psycopg pierde la sesión de solo lectura con el rollback | **SQLAlchemy 2.0.53 compila `TOP`, `FETCH FIRST` y `LIMIT`** según el motor | Aprobada (F02-R) |
| ARG-017 | `sniff` con errores; `stat` por fichero; MinIO | Se detecta DICOM primero; `scandir`; prefijos normalizados; digests de ruta; versitygw | DICOM salía como PDF; un `stat` por fichero es una ida y vuelta de red; las rutas llevan nombres de pacientes | **MinIO ya no publica imágenes comunitarias** (2026-09-14) | Aprobada (F02-R) |
| ARG-018 | `LDAP_MATCHING_RULE_IN_CHAIN`; filtros libres | Recorrido en anchura con detección de ciclos; filtros validados; LDAPS con la CA del cliente | Esa regla solo existe en AD; los filtros libres admiten consultas no previstas | **ldap3 2.9.1 devuelve `datetime`**, no FILETIME | Aprobada (F02-R) |
| ARG-019-020 | Rutas REST por prefijo; seguir `next`; DICOM con `assert` | Plantillas de ruta como regex completa; sin redirecciones; solo C-ECHO y C-FIND, con un test que prohíbe C-MOVE, C-GET y C-STORE; OAuth2 aplazado | El prefijo deja pasar `/patients-export`; `next` puede llevar el token a otro host; `assert` desaparece con `-O` | **pynetdicom 3.0.4 expone `send_c_move/get/store`**, así que había que prohibirlos | Aprobada (F02-R) |

## Fase 03 · Inventario y grafo

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-021-023 | Cypher con `MERGE…ON CREATE`, `sha1`, lotes mixtos | `GraphStore` con reglas de escritura compatibles con AGE; `natural_key` con sha256; instantáneas inmutables; desde F03-15, `SET +=` e índice GIN | En AGE 1.5.0 fallan `ON CREATE SET`, `reduce`, los lotes mixtos (`vertex … was deleted`)… | **Sondas sobre PostgreSQL 16.15 y AGE 1.5.0**; perfilado con 10 200 columnas: `*1..3` tardaba 1,5 s por sistema y `SET +=` bajó de 114 a 16 ms | Aprobada (F03-R); ampliada en F03-15 |
| ARG-024-025 | NUSS de dos ramas; diccionario por subcadena; IBAN como identificador oficial | Validadores puros; NUSS válido si cuadra cualquiera de los dos cálculos; diccionario por tokens; IBAN → `financial_data`; cola de revisión con tabla | La subcadena da falsos positivos (`lat`/`translation`); las fuentes del NUSS no coinciden | **Fuentes contrastadas (2026-09-15); ninguna de la TGSS** | Aprobada (F03-R) |
| ARG-026-028 | Vistas con `->>`; todas las parejas en flujos | Catálogo con `agtype_access_operator`, frescura e informe; detector por bloques | En AGE fallan `->>` y `::jsonb`; todas las parejas son unos 1,25·10⁹ pares | Sondas AGE (2026-09-15) | Aprobada (F03-R) |
| ARG-029-030 | Etiqueta interpolada; regex libre; `cron_schedule` | Etiquetas en lista blanca; prefijo de 100 caracteres como máximo; paginación; profundidad 4; `snapshot(id)`; Schedules de Temporal | Inyección Cypher; ReDoS; determinismo de Temporal | — | Aprobada (F03-R) |

## Fase 04 · Ontología

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-031-033 | Vocabulario en castellano; `ConjunctiveGraph`; vigencia por `now()` | Vocabulario en inglés con `@es` y enlace a DPV; vigencia tomada del manifiesto firmado; selector ampliado; catálogo provisional de retos | `now()` no responde qué versión aplicaba en una fecha; `ConjunctiveGraph` está en desuso | Sonda de rdflib 7.6; API de F03-12 | Aprobada (F04-00) |
| ARG-034-040 | SHACL, ODRL y Rego en castellano; Turtle con `str.format`; `publish.sh` con cosign y GNU | Formas y políticas en inglés; Turtle canónico con rdflib; OPA en el compose; 5 puertas del Plan Director; bundle firmado con Ed25519 | Las formas nunca casarían con valores en inglés; `str.format` es inyectable; no hay cosign ni herramientas GNU en Windows | — | Aprobada (F04-00) |

## Fase 05 · Motor de retos

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-041-042 | Esquema en castellano; plantillas `{{nodo}}` con `re.sub` | Esquema en inglés con traducción; parámetros tipados (`$node`, `$client`, `$campaign`); `compile_campaign` sobre la instantánea; catálogo generado | Los 27 ids ya estaban fijados; plantillas de texto dentro de SQL | — | Aprobada (F05-00) |
| ARG-043-047 | Compuertas en castellano; sello delegado a la F7; bucle que puede colgarse | Workflow con compuertas `start` y `sampling`, `unit_id` idempotente, reintentos por tipo de error y sello en la F05 (la API de campañas vive hoy en `argos_api`) | Los reintentos duplicaban veredictos; la prueba de la F05 exige el sello | — | Aprobada (F05-00) |
| ARG-045-046 | Vectores 385, **371** y 0,0099; veredicto binario; evaluador con E/S | Muestreo puro; **370**; cuatro valores sobre la cota de Wilson; `Decimal` con `ROUND_CEILING`; determinismo probado en Linux y Windows | El vector del documento está mal; `round` y `json.dumps` rompen el determinismo | **Cálculo a mano: n = 369,98 → 370** | Aprobada (F05-00) |
| ARG-048-050 | Estados en castellano; huella truncada; familias `cns-` e `ia-` | Máquina de estados cerrada en código y `CHECK`; huella completa `UNIQUE`; `WorkUnit` guardada en el veredicto; familias del catálogo de la F04 | Carrera de concurrencia; el `assert` impedía verificar cuando la biblioteca avanza | `schema_nucleo.sql` no existía | Aprobada (F05-00) |

## Fase 07 · Evidencia

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-062 | Artefacto con `emitido = now()` | `evaluated_at` = fecha del veredicto; el momento de escritura va al índice y a la versión del WORM | Con `now()`, un reintento del cierre da otro hash y el WORM rechaza la segunda escritura | — | **Escrita durante F07-05; falta que la revisemos** |
| ARG-064-065 | `SoftSigner` con la clave en disco; TSA cualificada | `VaultTransitSigner` marcado `non_production`; TSA local con `openssl ts`; TPM y TSA real como MANUAL | Ya existía una firma no exportable; no hay TSA cualificada en desarrollo ni en el CI | — | Aprobada (F07-00) |
| ARG-067 | PDF con WeasyPrint; momento de ensamblado | ReportLab invariante, construido solo desde el JSON, con su hash en el pie y QR | `markdown-pdf` depende de PyMuPDF (**AGPL**), excluida por ADR-0010; WeasyPrint pide GTK; el momento cambia el hash que cita la credencial | **Licencias revisadas**: PyMuPDF AGPL-3.0, ReportLab BSD | **Escrita durante F07-09; falta que la revisemos** |

## Fase 08 · Consola y APIs

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-071-080 | Roles y estados en castellano; `INSERT` propio en la API; «sello cualificado» y «TPM» en la interfaz; `.jsx` | Identificadores en inglés con los roles del realm; la API llama a las funciones del dominio; la evidencia se muestra como es, marca `non_production` incluida; `.tsx` | ADR-0005; una sola verdad por tabla; la firma aún no está en TPM y el sello no es cualificado | Roles del realm y estados ya construidos | Aprobada (F08-00) |

## Fase 09 · Seguridad de plataforma

| Nota | Documento pedía | Hicimos | Por qué | Qué comprobamos | Estado |
|---|---|---|---|---|---|
| ARG-081-090 | k3s, cert-manager, Kyverno, TPM; `/healthz`; cosign; `shell=True`; restauración con `postgres:16` | Paquetes en inglés; puerto `Orchestrator` (Compose hoy, Kubernetes con un doble); nunca `shell=True`; diario con `journal_pg`; restauración con la imagen del entorno | No hay k3s ni hardware; `shell=True` con nombres que llegan de un soporte es inyección de órdenes; `postgres:16` a secas no restauraría AGE | Conexiones con `trust`, contenedores sin restricciones y sin 2FA (revisado en F09-R) | Aprobada (F09-00) |
| ARG-085 | `DynamicPool` sobre `psycopg_pool` que se reconstruye al rotar; login por Kubernetes auth | La credencial dinámica en un fichero de servicio de libpq (`pg_service.conf`) que se sustituye entero; conexiones con `?service=argos`; AppRole por volumen en desarrollo; un contenedor acompañante para el gateway de IA | Ningún servicio usa pool: 141 `psycopg.connect(dsn)` en 48 módulos con la cadena fijada al arrancar; el gateway no alcanza Vault por diseño; no hay k3s | Contamos las llamadas; un test con TTL de 60 s rota, sigue conectando y ve desaparecer el usuario vencido; la revocación real (`REASSIGN OWNED` + `DROP ROLE`) se probó con tres roles | **Propuesta**, pendiente de aprobación |

## Pendiente común a todas las notas

La sección 6 de cada nota («actualizar el documento de fase») **no se ha hecho en ninguna**: los `.txt` de `docs/fases/` no citan sus notas ni sus ADR. Está en [la revisión](04-revision-2026-09-23.md) como tarea pendiente.
