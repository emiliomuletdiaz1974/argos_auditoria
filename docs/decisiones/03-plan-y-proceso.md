# 03 · Decisiones de plan, alcance y forma de trabajar

**Confidencialidad:** `internal` · [← índice](README.md)

Aquí se recogen dos tipos de decisión:

1. **DP-NN:** decisiones sobre alcance, orden y reglas de trabajo, tomadas en las tareas DECISIÓN o por indicación directa.
2. **Decisiones técnicas dentro de las tareas:** las que no merecían un ADR pero conviene poder encontrar, cada una con su motivo.

La fuente de todas es la bitácora del plan (`.scratch/plan/BITACORA.md`), que no se versiona.

---

## Decisiones de plan (DP)

### DP-01
**Base del proyecto (E0-03)** · 2026-09-14

- **Decidimos:** aceptar las cuatro recomendaciones:
  - ADR-0001: documentos de fase más el Plan Director; Packer y k3s aplazados;
  - ADR-0002: diario v1;
  - ADR-0003: uv y GitHub Actions;
  - ADR-0004: la web sale de la v7_1.
- **Por qué:** cada ADR comparaba las opciones y justificaba la recomendación (ver [01](01-arquitectura.md)).
- **Qué comprobamos antes:** antes de meterlo en las tareas, corregimos el código de referencia de los documentos:
  - calculamos a mano los vectores del diario;
  - probamos el compilador del banco de la web: 194/194 idénticos.

### DP-02
**Publicación de la web fuera de este plan (W-09)** · 2026-09-14

- **Decidimos:** marcar W-09 como `[-]`.
- **Por qué:** subir la web al subdominio no forma parte de este plan de trabajo.
- **Consecuencias:** el protocolo la trata como resuelta para las dependencias. Siguen abiertas dos cosas:
  - la revisión legal de W-07: la política de privacidad dice «mientras dure la relación» y la purga borra a los 12 meses;
  - la comprobación de `HTTP_AUTHORIZATION` en el hosting real.

### DP-03
**Código en inglés (F1-07 → ADR-0005)** · 2026-09-14

- **Decidimos:**
  - pasar todo el código de `argos/` a inglés y refactorizar lo ya construido;
  - dejar la documentación y git en español;
  - `argos-web` no se toca.
- **Por qué:** seguir la convención habitual en programación y dejar de mezclar idiomas.
- **Cómo se ejecutó:**
  - F1-07 se interrumpió y su trabajo se guardó en un `stash`;
  - se crearon R-01 (refactor) y R-02 (reescribir los planes);
  - F1-07 pasó a depender de R-02.

### DP-04
**Validación jurídica retenida (F04-00, punto 3)** · 2026-09-16

- **Decidimos:** retener F04-13, F04-15, F04-17 y F04-19 y el tag `fase-04` hasta tener un perfil jurídico-técnico.
- **Consecuencias:**
  - el protocolo **salta las tareas retenidas sin detenerse**;
  - el alcance del v1 se mantiene completo: RGPD, EHDS y AI Act.
- **Por qué:** no hay nadie con ese perfil asignado, y parar todo el programa por ello no tenía sentido. El contenido normativo queda marcado como «pendiente de validación jurídica» allí donde se usa.

### DP-05
**Rendimiento del grafo (F04-00 punto 5 y F03-15)** · 2026-09-16

- **Decidimos:** atacar el rendimiento ya, con una tarea nueva (F03-15). Al terminarla aceptamos el **criterio reformulado** (opción A): sin consultas de coste lineal y con la extrapolación de la talla `s` por debajo de los objetivos del §3.10.
- **Por qué:** en F03-14 medimos que el objetivo no se cumplía:
  - 9,5 h de inventario;
  - 14,9 h de reexploración, frente a un objetivo de 2 h.
- **Resultado medido:** 1,17 h de inventario y 1,02 h de reexploración.
- **Por qué no bastaba con el ratio de la tarea:** el ratio `xs`/`smoke` quedó en 59 % (se pedía 70 %). Penaliza justo quitar costes fijos, que era la mejora buscada; por eso cambiamos el criterio.
- **Descartamos:** seguir optimizando con una conexión reutilizada por sistema (opción B).

### DP-06
**Documentación técnica antes de seguir (etapa D)** · 2026-09-17

- **Decidimos:**
  - documentar las Fases 01–03 antes de continuar con la 04;
  - Markdown en el repositorio y PDF para entregar (`tools/docs_pack.py`);
  - documentos de módulo e informes de cierre como `client`; ADR, notas y plan como `internal`;
  - desde D-04, `make docs-check` rompe la verificación si falta un documento.
- **Por qué:** el producto se entrega a clientes que auditarán su documentación, y hacerla al final sale más caro y queda peor.

### DP-07
**Fase 04: verdad terreno provisional y cierre técnico** · 2026-09-17

- **Decidimos:**
  - **opción B** en F04-18: construir la verdad terreno de aplicabilidad sobre poblaciones sin validar, marcada como provisional;
  - aplicar las recomendaciones a las tres preguntas que abrió, lo que creó F04-21 a F04-24:
    - el clasificador reconoce referencias a pacientes y puntuaciones clínicas;
    - dato sindical en la fuente simulada;
    - revisión del DPO;
    - cifrado también sobre categorías especiales;
  - **opción A** en F04-99: cierre técnico con el tag `fase-04-tecnica` y una F04-98 retenida para el cierre jurídico.
- **Por qué:** avanzar a la Fase 05 sin esperar a la validación jurídica (DP-04), sin fingir que está hecha.

### DP-08
**Fase 05 (F05-00)** · 2026-09-17

- **Decidimos:**
  - aprobar ADR-0007, ADR-0008 y sus notas;
  - **cambio sobre la propuesta:** claves del DSL en inglés con una capa de traducción al castellano, igual que en la ontología.
- **Nota:** los puntos 6 y 7 se aprobaron con un «estoy de acuerdo» genérico.

### DP-09
**Fase 06 (F06-00)** · 2026-09-17

- **Decidimos:** aprobar ADR-0009 tal cual.
- **Además:** partir F1-11 en dos, `F1-11a` (imagen) y `F1-11b` (k3s). F1-11b recoge también las políticas de red de los conectores y del gateway.
- **Por qué:** la barrera de red del gateway de IA necesita k3s; la imagen, no.

### DP-10
**Fase 07 (F07-00)** · 2026-09-18

- **Decidimos:** aprobar ADR-0010, ADR-0011 y la nota ARG-064-065. El tag `fase-07` no espera al registro en un GXDCH (F07-14).
- **Por qué:** el GXDCH depende de un acceso externo que no controlamos.

### DP-11
**Fase 08 (F08-00)** · 2026-09-20

- **Decidimos:** aprobar ADR-0012, ADR-0013 y la nota. La prueba con un usuario de negocio sin acompañamiento es MANUAL (F08-98), y `F08-99` cierra la fase con el guion automático de Playwright y la suite de contrato.
- **Por qué:** la prueba con una persona no se puede automatizar; el guion automático demuestra lo mismo de forma repetible.

### DP-12
**Repositorio en GitHub** · 2026-09-21 (durante F08-09)

- **Decidimos:** subir el repositorio a `github.com/emiliomuletdiaz1974/argos_auditoria`.
- **Qué comprobamos antes:** que ese repositorio es **público**. Lo confirmamos igualmente.
- **Cómo se hizo:** el `push` lo hicimos a mano; `origin` queda configurado. La regla de no hacer `git push` desde el agente se mantiene.

### DP-13
**Verificación proporcional** · 2026-09-22

- **Decidimos:**
  - en una tarea normal se ejecutan los tests del módulo tocado y de lo que depende de él, más `lint`, `typecheck`, `docs-check` y `api-contract`;
  - `make check` completo solo en los cierres de fase y en los cambios transversales (migración, contrato, matriz de autorización, Makefile, CI, dependencias);
  - en la bitácora se escribe siempre qué se ejecutó.
- **Por qué:** la suite completa tarda de 25 a 45 minutos y no aporta nada en una tarea acotada.
- **Relacionado, aprendido en F08-17:** antes de culpar al código, mirar el entorno. El compose se cae de vez en cuando con contenedores en código 255, y tres intentos de verificación se perdieron por eso.

### DP-14
**Fase 09 (F09-00)** · 2026-09-23

- **Decidimos:**
  - aprobar ADR-0014 y la nota ARG-081-090 tal como se propusieron;
  - registro de seguridad en una tabla con su propia cadena, **no en Loki**;
  - TOTP solo para `platform_admin` y `dpo_reviewer`; el cliente decide en la implantación si lo extiende a `campaign_manager`;
  - integrar ya la rama `fix/auditoria-seguridad` (F09-17), antes de la revisión de seguridad.
- **Por qué:**
  - el ENS pide un registro de actividad íntegro, y una cadena se puede verificar;
  - los dos roles con TOTP son los que aprueban y deciden;
  - la rama tiene 21 hallazgos ya corregidos que la revisión no debe redescubrir.

### DP-15
**Lo que espera a terceros no bloquea el cierre** · varias fechas

- **Decidimos:** las tareas que esperan hardware, accesos o contratos son MANUAL y no bloquean el tag de su fase. Afecta a:
  - F1-11a y F1-11b;
  - F02-98 (entorno real de GDC);
  - F06-05 (pesos del modelo);
  - F06-98 (GPU);
  - F07-14, F07-15 y F07-16 (GXDCH, TPM, TSA y EDC reales);
  - F08-98 (usuario de negocio);
  - F09-90, F09-91 y F09-92 (hardware).
- **Por qué:** el programa no puede quedarse parado por dependencias externas. Cada informe de cierre las declara como pendientes y ningún documento las presenta como hechas.
- **Excepción:** la Fase 06 **no tiene tag**, porque F06-99 depende de F06-05 (pesos del modelo, MANUAL). Ver [revisión](04-revision-2026-09-23.md).

---

## Decisiones técnicas dentro de las tareas

Formato: `tarea` — **qué decidimos** — por qué (y qué medimos, si consta).

### Etapa W y andamiaje
- `W-02` — **`.gitattributes` con `eol=lf`** — con `autocrlf`, `index.html`, `.htaccess` y los `.sh` pasaban a CRLF y rompían la comparación byte a byte de W-08.
- `S1-01` — **el Makefile no fija `SHELL := bash`** — en Windows `bash` resuelve al lanzador de WSL; las recetas se escriben válidas en sh y en cmd.
- `F1-04b` — **`make cover` ejecuta todos los tests** — la cobertura daba 80,00 % justo porque el diario y las migraciones solo se ejercitan en integración.
- `R-01` — **`docker compose down --remove-orphans` antes de renombrar servicios** — se quedó un contenedor huérfano ocupando el 8001.

### Fase 02
- `F02-R` — **fuentes simuladas repartidas en tres tareas intercaladas** — en lugar de un F02-00 monolítico. Además: MinIO sustituido por versitygw y Orthanc 26.9.0, porque la 24.9.3 no existe.
- `F02-04/07` — **no ejecutar la integración `heavy` (Oracle y SQL Server)** — solo quedaban 2,1 GB de RAM libres de 15,7 y Docker ya se había caído. Queda en pendientes.
- `F02-05` — **`LIMIT` como literal** — psycopg añade `::INTEGER` y rompe `text()`.
- `F02-09` — **`entry.smb_info` en lugar de `stat()`** — `stat()` conecta al 445 sin la sesión y podría mandar la autenticación a otro servidor.
- `F02-10` — **`params=None`** — en httpx 0.28, `params={}` borra la query.
- `F02-11` — **configuración `tls_valid_names`** — ldap3 no compara con los SAN de IP.
- `F02-14` — **`Cache-Control: no-cache` en FHIR** — HAPI cachea las búsquedas unos 60 s y la evidencia saldría desfasada.

### Fase 03
- `F03-00` — **`--renew-anon-volumes`** — el volumen anónimo reutilizado impedía aplicar las semillas.
- `F03-02` — **claves de categoría en `.gitleaksignore` sin tocar la migración** — la migración ya estaba aplicada y su checksum habría cambiado.
- `F03-03` — **lotes `UNWIND` separados en nodos y aristas** — el error `vertex … was deleted` de AGE 1.5.0, aislado con sondas.
- `F03-13` — **Schedule de reexploración pausado en desarrollo** — para no cargar el entorno.
- `F03-14` — **no ejecutar el perfil `m`** — la extrapolación superaba las 4 h del paso 6. Llevó a DP-05.

### Fase 04
- `F04-R` — **aplazar la descomposición a F04-R2** — escribir las tareas antes de aprobar el ADR arriesgaba rehacerlas.
- `F04-R2` — **vigencia por fecha de campaña; «dato personal» cubre las cinco clases** — también se corrigieron las dependencias de siete tareas.
- `F04-01/03` — **escribir siempre con `newline="\n"`; sufijo `Error` en las excepciones (regla N818)** — ficheros deterministas en Windows y en Linux.

### Fase 05
- `F05-R` — **`sample_size(10000) = 370`** — el documento decía 371 y lo recalculamos (ver ARG-045-046).
- `F05-01` — **la cuenta plantada va en MariaDB y no se siembra PostgreSQL** — PostgreSQL ya incumplía por sí solo (`ssl=off`).
- `F05-06` — **frescura del catálogo en `make challenge-catalog`, no en las puertas** — evitar un ciclo de dependencias.
- `F05-07` — **UUID5 por semilla, rango de DNI propio y solo hashes guardados** — reproducible y sin datos que parezcan reales.
- `F05-10` — **ampliar `argos.campaigns` en lugar de crearla; se retira `awaiting_start`** — la tabla ya existía.
- `F05-14` — **un reto reservado da `unverifiable`; el calendario de conservación es parámetro del cliente** — no inventar evidencia que no existe.
- `F05-18` — **4 ids siguen reservados** — no hay de dónde sacar su evidencia.
- `F05-99` — **en la verdad terreno, `inconclusive` → `unverifiable` para esos 4 ids, con el motivo escrito**.

### Fase 06
- `F06-R` — **la barrera primero y los conjuntos dorados segundos** — la invariante «ningún camino del LLM al veredicto» tenía que existir antes que el LLM.
- `F06-01` — **la mitad de red de la barrera se mueve a F06-13** — el contenedor todavía no existía.
- `F06-04` — **cuota por defecto cero** — lo que no se configura no consume.
- `F06-08` — **techo de confianza de 0,8 con menos de 50 decisiones; la confianza declarada se guarda aparte de la calibrada** — no fiarse del modelo sin datos.
- `F06-09` — **una sonda generada que escribe se rechaza, no se repara** — reparar ocultaría el intento.
- `F06-10` — **no se admite aritmética en las cifras de los dictámenes** — toda cifra debe existir tal cual en la fuente.
- `F06-11` — **JSON sobre `chat_json` en lugar del tool-calling nativo** — una sola vía controlada por el gateway.
- `F06-12` — **embebedor con señal en lugar de bajar el umbral** — el RAG pasó de 0,68 a 1,0, y el criterio nuevo solo lo pasan 0 de 5000 embebedores de ruido.

### Fase 07
- `F07-02` — **`verify_proof` recibe el tamaño del árbol** — sin él, una prueba de inclusión se puede reinterpretar.
- `F07-04` — **VersityGW, porque pasa la prueba de conformidad** — el test comprueba la garantía, no el informe de retención.
- `F07-05` — **fecha del veredicto en el artefacto (ARG-062) y sin clave foránea en `evidence_index`** — hash estable ante reintentos.
- `F07-06` — **`non_production` lo decide el firmante, no quien llama**.
- `F07-09` — **ReportLab (ARG-067)** — licencias: PyMuPDF es AGPL y WeasyPrint pide GTK.
- `F07-12` — **la cláusula de «atribución» queda fuera del catálogo ODRL** — no es verificable.
- `F07-13` — **la evidencia se dispara por el bus** — sin acoplar el motor de retos al servicio de evidencia.

### Fase 08
- `F08-02` — **la suite exhaustiva de autorización va en `tests/contract`** — así entra en el CI, que no levanta el entorno.
- `F08-03` — **clase de ruta y no middleware para idempotencia y diario** — el middleware no sabe quién llama y dejaría asiento de llamadas denegadas.
- `F08-06` — **el dominio prohíbe a un usuario cerrar un hallazgo o llevarlo a `reopened`** — solo la reejecución cierra.
- `F08-07` — **`credentials.create` pasa de `campaign_manager` a `dpo_reviewer`** — lo fija ARG-077.
- `F08-08` — **el agente del asistente vive en el gateway; la API solo llama; 503 honesto si no hay modelo**.
- `F08-09` — **`webhooks.read` solo para `platform_admin`; el secreto del webhook solo en Vault**.
- `F08-10` — **`--accent-strong` y ajustes de contraste AA sin tocar los colores de marca**.
- `F08-16` — **`console-e2e` fuera de `make check`** — `make check` no descarga navegadores.
- `F08-17` — **pausa por cortacircuitos de 300 s como máximo (`PAUSE_MAX`)** — nadie envía `circuit_closed`, y sin tope la campaña esperaría para siempre.
- `F08-99` — **`GET /api/v1/approvals` sigue en 501, declarado** — la consola no lo necesita; no se implementa en una tarea de cierre.

### Fase 09
- `F09-R` — **añadir roles de base de datos por servicio, MFA y registro de seguridad**, que el documento de fase no traía y el Plan Director pide; **revisión de F1–F8** (no F1–F7), porque la Fase 08 ya estaba cerrada; **F09-17** para integrar la rama de auditoría.
- `F09-01` — **la revisión cruzada del modelo de amenazas es un test**, no una lectura: toda mitigación `implementada` tiene que apuntar a rutas que existen en el repositorio, o `tests/docs/test_threat_model.py` falla. Así el modelo no puede afirmar más de lo que hay.
- `F09-01` — **el test comprueba el formato del identificador de tarea, no que exista en la tabla del plan** — la tabla vive en `CLAUDE.md`, fuera del repositorio, y el test tiene que pasar también en el CI. El componente `ARG-NNN`, en cambio, es obligatorio en cada mitigación.
- `F09-01` — **las correcciones de la auditoría del 2026-09-18 cuentan como `en desarrollo` (F09-17)** — están en una rama sin integrar, no en `main`, y el modelo solo da por hecho lo que está en `main`.
- `F09-02` — **lectura dirigida en cinco superficies en paralelo, además de las herramientas** — las reglas `S` de ruff ya estaban activas desde S1-01 y no marcaban nada, y `/security-review` revisa cambios pendientes, no un repositorio entero. Lo que encuentra fallos de lógica (confianza en lo que trae el bundle, presupuesto que se recrea, doble control que depende de un campo) es leer el código con el modelo de amenazas delante. Repartimos por superficie para que cada revisión fuera profunda.
- `F09-02` — **ningún hallazgo se registra sin comprobarlo en el código** — los más graves se reprodujeron ejecutando el código real: evasiones del validador SQL, prueba de Merkle, `did:web`, depuradores. El resto lleva archivo y línea, y la columna «Verif.» dice cuál es cuál (C/L).
- `F09-02` — **las correcciones se agrupan por componente en 12 tareas (F09-20…F09-31)** en lugar de una por hallazgo — 57 tareas habrían repetido el mismo contexto y los mismos archivos; agrupadas, cada tarea toca un componente con una sola revisión cruzada. Cada tarea empieza por tests que reproducen sus hallazgos.
- `F09-02` — **las tareas de corrección van antes en la tabla que el resto de la fase** — son fallos de lo ya construido, varios altos (el comprobador acepta evidencia falsa, un validador de solo lectura evadible, un presupuesto de carga que no limita). Seguir construyendo encima sin arreglarlos sería apilar controles sobre cimientos que no cumplen.
- `F09-02` — **SEC-057 (`vitest`) se acepta hasta F09-09** — es una dependencia de desarrollo que no viaja en la imagen, y la puerta de vulnerabilidades de F09-09 es el sitio para decidir entre actualizar a la versión mayor o una excepción con caducidad.
- `F09-02` — **el modelo de amenazas se corrige a la baja (v1.2)** — ocho mitigaciones que daba por «implementadas» tienen huecos y vuelven a «en desarrollo» con su tarea. Mejor un modelo que dice menos y es cierto que uno que un auditor desmonte.
- `F09-22` — **el estado del presupuesto en PostgreSQL y no en Redis ni en NATS KV** — el diario de consultas y los sistemas ya viven en PostgreSQL. Una fila por sistema con `SELECT … FOR UPDATE` y el reloj de la base basta para que varios procesos y hosts compartan fichas. Así no se añade otro almacén que operar ni que respaldar.
- `F09-22` — **la regla sigue siendo una sola; solo cambia dónde vive el estado** — `LoadBudget` mantiene sus reglas (fichas, ventanas, cortacircuitos) y guarda el estado en un almacén: en memoria para las pruebas y un proceso, en PostgreSQL para el sistema. Los 18 tests que ya existían del presupuesto pasan sin tocarlos, y los nuevos comprueban lo compartido.
- `F09-22` — **una sonda de prueba abandonada caduca con el enfriamiento** — si el proceso que tenía la prueba del semiabierto muere, el sistema no puede quedarse bloqueado para siempre. Es la «caducidad de la reserva» que pedía la revisión cruzada de la tarea.
- `F09-22` — **la exploración SQL es una sentencia literal sobre el catálogo, no el inspector de SQLAlchemy** — el inspector lanzaba una consulta por esquema y otra por tabla (más de 20 000 en un ERP grande) sin diario ni presupuesto. Registrar cada una y cobrarle ficha habría convertido la exploración en horas al ritmo pactado de 30 por minuto. Una sola sentencia es a la vez auditable y barata. Comprobamos antes que la verdad terreno no fija el formato del tipo de columna, que solo usa como contexto la clasificación asistida.
- `F09-22` — **`follow_up` para toda petición que no es la sonda misma** — las páginas que elige el servidor REST y la asociación DICOM también son peticiones al sistema del cliente. Un único mecanismo del SDK las registra y las paga, en lugar de que cada conector lo resuelva a su manera.
- `F09-21` — **lista blanca solo para las funciones que sqlglot no modela, no para todas** — la tarea proponía una lista blanca completa. Comprobamos que las sondas de catálogo y la biblioteca usan muchas funciones estándar (agregados, fechas, cadenas) que sqlglot reconoce y que no escriben, y que el riesgo real estaba en las funciones que no reconoce: las del usuario, que en Oracle pueden confirmar escrituras con una transacción autónoma. Esas pasan solo si son de catálogo (`ALLOWED_ANONYMOUS`); las reconocidas pasan salvo las denegadas, y la lista de denegadas se compara ahora con cada segmento del nombre. La biblioteca de retos, los conectores y los conjuntos dorados del generador siguen validando; solo hubo que añadir `aclexplode`, que usa la sonda de privilegios de PostgreSQL.
- `F09-21` — **se rechazan todas las pistas de SQL Server, también `NOLOCK`** — `NOLOCK` no bloquea, pero lee datos no confirmados. Ninguna sonda la necesita, y una regla sin excepciones es más fácil de auditar.
- `F09-21` — **las evasiones van al arnés común (`SQL_WRITE_ATTEMPTS`) y no a un test aparte** — ese arnés ya lo recorren el test puro en los cinco dialectos y la integración contra las fuentes reales, que comprueba que el intento se rechaza y queda en el diario sin llegar al motor. Así la integración contra MariaDB que pedía la tarea sale sin duplicar pruebas.
- `F09-20` — **la confianza del comprobador va en un fichero de configuración y no dentro del bundle** — quien falsifica evidencia también puede falsificar el documento DID y la autoridad de sellado que la acompañan. La alternativa estándar, resolver `did:web` por red, no sirve a un comprobador que tiene que trabajar sin conexión. Sin anclaje configurado, el informe dice «emisor no anclado» y no es `ok`, en lugar de suponer confianza.
- `F09-20` — **el contenido del expediente lo respalda la credencial, sin una segunda firma nueva** — el expediente se escribe después de firmar la raíz y cita esa firma, así que no puede ir dentro de ella sin dependencia circular. La credencial ya es la declaración firmada del emisor sobre el SHA-256 del expediente (ADR-0011). Un expediente se entrega a terceros junto con su credencial; sin ella, el comprobador dice que nada firmado respalda su contenido. Una credencial revocada sigue autenticando quién afirmó el expediente: la revocación se informa aparte.
- `F09-20` — **la lista de estado caduca a las 24 h y se sirve firmada desde una caché** — sin caducidad, un paquete guardado antes de revocar dice «no revocada» para siempre. Firmando en cada petición, el endpoint público haría trabajar al firmante a quien quisiera. Se vuelve a firmar cuando cambia una revocación o ha pasado la mitad de su vida, así que un comprobador tiene siempre horas y no segundos.
- `F09-20` — **`--at` en el CLI para comprobar un paquete archivado a su fecha** — el plan B de la demo es un paquete archivado. Comprobarlo «hoy» haría fallar siempre su lista de estado. Comprobarlo a la fecha de su lista dice la verdad sobre ese momento.
- `F09-17` — **fusión (merge) y no rebase de `fix/auditoria-seguridad`** — conserva los 40 commits con su fecha y su mensaje, que son la evidencia de cuándo se corrigió cada hallazgo; un rebase los habría reescrito.
- `F09-17` — **en hallazgos se conservan las dos reglas** — `main` impedía a una persona llevar un hallazgo a `closed_compliant` o `reopened`, y la auditoría exigía que solo `system:remediation` cerrara (también frente a otros actores `system:`). No se contradicen: juntas en `check_request`, y el test de integración comprueba las dos.
- `F09-17` — **el endurecimiento de la API de campañas se traslada a la API única, no se descarta** — la API de la Fase 05 ya no existía (F08-17), pero sus defectos (ids sin validar, cuerpos sin límite, errores de la base con detalle, `/docs` abierto, sujeto sintético sin campaña) podían repetirse en `argos_api`. Comprobamos cuáles ya cubría (UUID tipados, `approvals_needed` compartido) y trasladamos el resto con tests que vimos fallar antes.
- `F09-17` — **`/api/v1/docs` y el contrato servido solo en desarrollo** — misma decisión que la auditoría para la API retirada: fuera de desarrollo describiría rutas y roles a cualquiera de la red. El contrato versionado se sigue generando de `openapi()`, así que la consola y los clientes no pierden nada.
- `F09-17` — **todo proceso abre el bus con `bus_from_config`, vigilado por un test arquitectónico** — al fusionar vimos que los procesos añadidos después de la auditoría (worker de campañas reescrito, worker de evidencia y worker de webhooks) abrían NATS sin usuario: con NATS autenticado se habrían quedado fuera sin avisar.
- `F09-17` — **usuario de NATS propio de solo escucha para `webhook-worker`, y fuera NATS y OPA de la API y de `evidence-api`** — mínimo privilegio: la API y `evidence-api` no usan ninguno de los dos; `evidence-api` hereda por ancla YAML la identidad `evidence` de su servicio, que es de su misma familia.
- `F09-01` — **cada riesgo residual lleva quién lo acepta** — el organismo (medidas físicas y de personal, talla elegida) o nosotros (texto del LLM, material de desarrollo marcado `non_production`, vulnerabilidades sin parche con excepción que caduca).
