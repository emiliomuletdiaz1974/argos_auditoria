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
- `F09-25` — **el contenido firmado se comprueba donde se ejecuta, y no se carga desde el bundle** — el worker lee la biblioteca de su disco y OPA de su propio montaje. Antes de cada campaña comparamos las dos cosas con el manifiesto firmado de la versión en vigor (`verify_on_disk`, y `verify_running_policies` sobre `GET /v1/policies`). La tarea proponía firmar también un bundle de OPA (`--verification-key`). Lo descartamos porque añadía un segundo formato de firma y una segunda clave para el mismo contenido. Además, preguntar a OPA qué tiene cargado cubre lo que de verdad ejecuta, y no solo lo que hay en su disco.
- `F09-10` — **el actualizador de desarrollo corre en el anfitrión y no en un contenedor** — nota de desviación ARG-086, propuesta. Compose resuelve las rutas de los volúmenes en el cliente, y desde un contenedor en Docker Desktop no existen. Además, el contenedor necesitaría el socket de Docker, que da el control del anfitrión.
- `F09-10` — **la identidad de una imagen exportada depende del formato** — con el almacén de imágenes de containerd, `docker save` escribe un layout OCI. Comprobamos con la imagen real del servicio de ejemplo que su `Id` es el digest del índice de `index.json`, no el de la configuración. El actualizador comprueba ese digest y que cada blob coincide con su nombre. Con el formato clásico sigue valiendo el digest de la configuración.
- `F09-10` — **se apunta en el plan la imagen anterior de cada servicio antes de cambiarlo** — así `recover()` sabe volver aunque el proceso muera justo después de la orden. Lo prueba el test con un orquestador que «muere» a mitad.
- `F09-10` — **la API verifica antes de encolar y el actualizador vuelve a verificar al aplicar** — la cola es una carpeta. Una petición escrita a mano no se salta nada: el actualizador verifica siempre.
- `F09-10` — **la petición nombra un paquete de la bandeja, nunca una ruta** — la API y el actualizador ven carpetas distintas (contenedor y anfitrión), y una ruta permitiría señalar fuera de la bandeja. El nombre pasa un patrón estricto.
- `F09-10` — **los tests de la ruta de la API y los del formato OCI se escribieron después de su código** — los de la ruta los vimos fallar después, retirando la ruta de la aplicación. Los del formato OCI nacieron de encontrar el problema con un archivo real.
- `F09-10` — **la prueba de integración usa el servicio de ejemplo y lo deja como estaba** — construye una imagen buena y una que nunca queda sana a partir de la que corre, las firma con la clave de release de desarrollo (Vault transit) y aplica los dos paquetes. Al terminar, pase lo que pase, devuelve el servicio a su imagen original.
- `F09-09` — **syft 1.52.0 y grype 0.119.0, fijados por digest, y no las versiones de 2024** — con grype 0.86 (esquema 5) comprobamos que la base de vulnerabilidades era del 9 de marzo de 2026, seis meses atrás. La del esquema 6 se construye a diario, y grype rechaza una base de más de cinco días. El CI guardaba el SBOM en SPDX con syft 1.14 por etiqueta; ahora es CycloneDX, como pide la tarea, y todo va fijado por digest.
- `F09-09` — **una alta bloquea si su corrección se observó hace más de 30 días, o si no hay fecha** — grype 0.119 da la fecha en que se vio cada corrección (`fix.available[].date`). Sin fecha nadie puede decir que sea reciente, así que bloquea. El umbral de la tarea (30 días) se mantiene; no hizo falta tocar el ADR.
- `F09-09` — **una excepción caducada rompe la puerta aunque ya no haya hallazgo** — así quien la concedió vuelve a mirarla. Una excepción sin justificación, autor o caducidad no se carga.
- `F09-09` — **`make build` construye las seis imágenes** — solo construía tres (ejemplo, motor y gateway): faltaban la API, la evidencia y el comprobador, y la release no las listaba. Ahora cada una tiene su SBOM, y una imagen sin SBOM no entra en el manifiesto.
- `F09-09` — **el SBOM de la consola es el de lo que viaja** — syft, sobre `package-lock.json`, recoge las dependencias de ejecución (React, SWR…), que son las que acaban en los ficheros construidos. `vitest` es de desarrollo y no aparece. SEC-057 (GHSA-82fw-gwwq-j7x9, moderada, corregida en vitest 4.1.11, y npm propone la 5) queda en `vex.yaml` con caducidad del 2026-12-31. `npm audit` sigue siendo la herramienta para las dependencias de desarrollo.
- `F09-09` — **el primer `make sbom` pasa con 0 bloqueantes y 300 avisos** — son todos altas del sistema base Debian 13 marcadas `wont-fix` o `not-fixed` (util-linux, glibc, perl, zlib), más una de Python 3.12.14 cuya corrección solo existe en 3.14.0b1 y se observó el 2026-09-18. Ninguna se ha exceptuado, porque ninguna bloquea. Revisarlas al cambiar de imagen base queda en pendientes.
- `F09-09` — **la política de Kyverno exige firma y digest, pero la firma de las imágenes llega con el registro del appliance** — `verify-images.yaml` lleva un marcador en lugar de la clave pública, que se pone en la instalación (F09-92). Hoy las imágenes no se firman. Queda en pendientes.
- `F09-08` — **el registro de seguridad reutiliza la función de hash y el verificador del diario v1, con otro génesis** — `security.append` calcula el hash con `argos.journal_hash` y exige la forma canónica con `argos.journal_canon`. `verify_chain` usa `verify_entries` del diario con el génesis `ARGOS-SECURITY-GENESIS`. Así no se copia el algoritmo, y ninguna de las dos cadenas se puede empalmar con la otra.
- `F09-08` — **el hash cubre el tipo y un `payload` canónico `{detail, outcome, source}`, y la verificación también compara las columnas** — las columnas `source`, `outcome` y `detail` existen para consultar. Al escribir los tests vimos que una manipulación de `detail` no rompía la cadena, así que `verify_chain` comprueba además que coinciden con lo que cubre el hash. Tiene su test.
- `F09-08` — **las ráfagas se pliegan por (tipo, resultado, origen): 10 eventos por minuto y un resumen con la cuenta** — lo pedía la revisión cruzada. El origen es la persona si hay identidad y la IP si no. Lo probamos con 200 tokens falsos seguidos: como mucho 11 filas, y la suma de lo plegado da 200. El resumen se escribe al cerrarse la ventana o al vaciar el registrador; lo que quede pendiente si el proceso muere se pierde, y está en pendientes.
- `F09-08` — **en el detalle, la plantilla de la ruta y no la ruta** — una ruta como `/inventory/nodes/{node_key}` puede llevar datos del cliente en el parámetro. El test lo comprueba con los depuradores de ARG-060 sobre todos los eventos.
- `F09-08` — **las métricas las publica la API desde la propia tabla** — ningún servicio tenía métricas Prometheus. El contador sale de un registro de solo añadir, así que es monótono, y cada lectura verifica la cadena entera. Hacerla incremental queda en pendientes.
- `F09-08` — **la expresión de la alerta de ráfaga usa una cadena literal de PromQL** — con `"auth\\..*"` Prometheus no cargaba las reglas («unknown escape sequence»). Lo vimos en el registro del contenedor al arrancarlo, y el test ejecuta `promtool check rules` dentro del contenedor.
- `F09-08` — **los fallos de inicio de sesión en Keycloak no entran en este registro** — son eventos de Keycloak, no de la API. Este registro recoge lo que llega a la API con un token. Integrar los eventos de Keycloak queda en pendientes.
- `F09-07` — **el TOTP se pide por un rol compuesto `mfa_required`, que heredan `platform_admin` y `dpo_reviewer`** — la condición «rol de usuario» de Keycloak admite un solo rol por paso. Con un rol compuesto, extenderlo a `campaign_manager`, como permite DP-14, es añadirle una línea en el realm.
- `F09-07` — **los permisos con segundo factor van en una lista `_second_factor` de la matriz, y la API no arranca si alguno lo tiene un rol sin TOTP** — un permiso así no lo podría ejercer nadie de ese rol. Además de los cinco de la tarea (compuertas, hallazgos, riesgo, revocación, integraciones) entran emitir credenciales, autorizar inyecciones y decidir columnas en revisión: son los otros actos del DPO que cambian algo.
- `F09-07` — **comprobamos antes en un realm desechable que Keycloak 26.0 emite `amr`** — solo lo hace con el mapper `oidc-amr-mapper` y una referencia (`default.reference.value`) en cada autenticador; sin ellas, el `amr` salía vacío. También comprobamos que el secreto TOTP sembrado y el HMAC-SHA-256 calculado en los tests coinciden.
- `F09-07` — **contraseñas de desarrollo importadas ya derivadas (PBKDF2-SHA512)** — con la política de contraseñas activa, Keycloak rechazaba importar `test` en claro («Password policy not met»); con la credencial derivada, como la exporta el propio Keycloak, se importa y la política sigue valiendo para toda contraseña nueva. Lo comprobamos en el realm desechable.
- `F09-07` — **la vuelta a iniciar sesión usa `prompt=login` además de `acr_values=otp`** — el realm pide el código por rol en cada inicio de sesión con formulario. No configuramos niveles de autenticación (LoA), así que `acr_values` sirve de indicación y `prompt=login` fuerza el paso por el formulario.
- `F09-07` — **los tests con tokens reales comparten un gestor de ventanas TOTP y limpian los fallos que provocan** — Keycloak rechaza un código ya usado. También rechaza el intento que llega justo después de un fallo aunque sea válido: lo vimos reproduciendo la secuencia. Un código sirve para un inicio de sesión cada 30 s, y el test que falla a propósito borra el estado de fuerza bruta del usuario.
- `F09-07` — **tras un código rechazado, Keycloak 26.0 da un `amr` sin `pwd`** — lo vimos en el flujo de navegador. La API solo exige `otp`, así que no afecta. El test del navegador comprueba `otp` y lo explica.
- `F09-06` — **`sslmode=verify-full` en la cadena de conexión de ARGOS, nunca `PGSSLMODE`** — la primera versión exportaba `PGSSLMODE`. El `make check` completo falló en 75 pruebas: la variable llegaba también a las conexiones de los conectores con las fuentes simuladas del cliente, que no tienen TLS («server does not support SSL», 105 veces en el registro). El TLS de una fuente lo decide su conector (F09-31). Los tests del host usan el modo por defecto de libpq (`prefer`), que negocia TLS con este servidor; la verificación con la CA la prueba `test_mtls.py`.
- `F09-06` — **la recarga del servidor cambia el contexto en `sni_callback`, no modificando el contexto en uso** — cambiar el certificado de un `SSLContext` mientras otros hilos lo usan no es seguro. Cada apretón de manos recibe un contexto nuevo cuando los ficheros han cambiado. Comprobamos que la recarga funciona también cuando el cliente no envía SNI (conexión por IP).
- `F09-06` — **un volumen `tmpfs` por servicio para su certificado** — así la clave privada solo la ve su servicio y el emisor. Los de PostgreSQL y NATS se copian y recargan con un envoltorio, porque PostgreSQL solo acepta una clave de su propio usuario con modo `0600`. El de Vault es `0755` porque Vault solo necesita leer la CA como su usuario.
- `F09-06` — **el emisor reemite también cuando cambia la CA raíz** — el Vault de desarrollo genera otra CA cada vez que se reinicia, y un certificado aún joven de la CA anterior dejaría de verificar.
- `F09-06` — **nats-py pasa a TLS en cuanto el servidor lo exige, así que las URL `nats://` de los tests siguen valiendo** — `Bus` toma el certificado de `ARGOS_TLS_DIR` si no se le da. En el compose las URL pasan a `tls://`, que es lo que exige la configuración en producción.
- `F09-06` — **los streams los crea un usuario `platform` al arrancar (`tools/nats_streams.py`), no cada servicio al conectar** — lo pide SEC-026. Los permisos de cada usuario enumeran sus *durables* uno a uno, porque NATS no admite comodines parciales (`webhooks-*` no es un comodín válido).
- `F09-06` — **el inventario sin `argos.campaign.>`** — comprobamos antes que el aviso de cortacircuitos (`argos.campaign.circuit_open`) solo lo cablea el worker de campañas; el planificador del inventario no lo usa.
- `F09-06` — **las sondas de permisos de NATS no pueden cambiar nada aunque el permiso exista** — la primera versión del test mandaba un `STREAM.UPDATE` con asuntos de prueba y `CONSUMER.DELETE` sobre *durables* reales. Con los permisos anteriores habrían cambiado los streams y borrado consumidores del entorno. No llegó a pasar, porque aún no había TLS y no conectaron, y lo comprobamos leyendo los streams. Ahora las sondas usan una configuración vacía y consumidores inexistentes.
- `F09-06` — **el test de consumo del inventario con un *durable* inventado pasa a comprobar que se rechaza** — era justo lo que SEC-026 prohíbe. Que el inventario sí puede con el suyo lo comprueba `test_mtls.py` sin tocar el consumidor real.
- `F09-06` — **no hay `verify=False` ni `CERT_NONE` en el producto, y un test lo vigila** — `tests/security/test_tls_verification.py` lee el código y la configuración. La única mención admitida es el docstring del conector SQL que explica por qué se rechaza `sslmode=require`.
- `F09-06` — **el software de terceros del entorno de desarrollo sigue en claro dentro de la red de Docker** — Temporal, Keycloak, OPA, la TSA y el EDC simulados. La tarea limita el alcance a los enlaces entre servicios de ARGOS, PostgreSQL y NATS. Queda en pendientes para el appliance (F09-92).
- `F09-05` — **la credencial dinámica va en un fichero de servicio de libpq y no en un pool** — nota de desviación ARG-085, propuesta. Contamos 141 `psycopg.connect(dsn)` en 48 módulos, todos con la cadena fijada al arrancar, y ningún pool. libpq lee el fichero en cada conexión nueva, así que la rotación no toca esos módulos y las conexiones abiertas terminan con su credencial.
- `F09-05` — **la credencial se renueva pidiendo otra, no prorrogando la concesión** — prorrogar no pasa del `max_ttl`, así que al final habría que pedir otra de todos modos. Pedir otra siempre da un solo camino, y el usuario viejo vence con su concesión.
- `F09-05` — **el token del AppRole dura 72 h, lo mismo que la credencial más larga** — Vault revoca las concesiones de un token cuando el token vence. Con un token de una hora, la credencial de 24 h habría desaparecido a la hora.
- `F09-05` — **`vault_admin` con `ADMIN OPTION` sobre los roles de servicio y `createrole_self_grant = 'set, inherit'`** — la revocación del documento (`REASSIGN OWNED` + `DROP ROLE`) necesita los privilegios del usuario efímero y los de su rol. Lo comprobamos revocando concesiones reales de `svc-api`, `svc-ai-gateway` y `svc-evidence`. El administrador tiene de hecho el poder de los roles de servicio, porque puede crear miembros suyos; por eso su contraseña la rota Vault nada más configurarse y solo Vault la conoce.
- `F09-05` — **Vault guarda las contraseñas con SCRAM (`password_authentication=scram-sha-256`)** — Vault 1.17 lo admite. El `CREATE ROLE` lleva el hash y no la contraseña, así que nada en claro llega al registro de PostgreSQL.
- `F09-05` — **el gateway de IA recibe su credencial de un contenedor acompañante** — el gateway no alcanza Vault (F06-13). El acompañante ejecuta el mismo código (`python -m argos_common.dynamic_db`) y comparte con él un volumen `tmpfs` con uid 10001 y modo `0700`, de solo lectura para el gateway.
- `F09-05` — **`role_id` y `secret_id` por volumen, y `PGSERVICEFILE` en el compose** — por volumen para que no aparezcan en `docker inspect`, que lo comprobamos en los ocho contenedores. `PGSERVICEFILE` va en el compose para que cualquier proceso del contenedor (también un `docker compose exec`) lea la misma credencial.
- `F09-05` — **los usuarios fijos de F09-04 se borran en cada `make dev`** — `ARGOS_DATABASE_PASSWORD_FILE` queda en la configuración para despliegues sin Vault, pero el entorno de desarrollo ya no tiene ninguna contraseña de servicio de larga vida.
- `F09-26` — **una tabla de permisos del diario (`argos.journal_grants`) y no una función `SECURITY DEFINER` por rol** — la tarea dejaba elegir. Una sola función con una tabla deja la regla a la vista, con un motivo por fila, y no multiplica el código que calcula el hash. Los patrones son `LIKE`: un actor sin `%` es exacto, así que `system:ai-gateway-x` no pasa por `system:ai-gateway`.
- `F09-26` — **el actor del gateway es `system:ai-gateway` y no `ai:gateway`** — la tarea proponía `ai:gateway`, pero el gateway siempre ha asentado como `system:ai-gateway` (`argos_ai/quotas.py`). Cambiarlo habría partido en dos nombres la historia del diario. Sus acciones quedan limitadas a `ai.*`.
- `F09-26` — **cuenta el usuario de la sesión, y el superusuario no se restringe** — dentro de una función `SECURITY DEFINER`, `current_user` es el dueño, así que se mira `session_user` y su pertenencia a cada rol. Un superusuario podría escribir la tabla directamente, así que restringirlo no protege nada. Las migraciones y los tests del producto entran así.
- `F09-26` — **los permisos se escribieron desde el código de cada servicio** — comprobamos los actores que usa cada uno: la evidencia solo `system:evidence`, el ejemplo `system:argos-example`, el gateway `system:ai-gateway`. La API, el worker de campañas y el inventario escriben varios actores `system:`. Solo la API escribe en nombre de una persona (`user:%`), porque es la única que recibe a las personas.
- `F09-26` — **la forma canónica se comprueba reconstruyéndola en el motor** — `argos.journal_canon` rehace el texto de ADR-0002 (claves por punto de código con `COLLATE "C"`, sin espacios, solo enteros) y se compara con lo recibido. Comprobamos con siete cargas difíciles (acentos, caracteres de control, separadores de línea, enteros de 20 cifras) que lo que canoniza Python lo acepta el motor, y que la clave duplicada, el espacio, el orden, el decimal y el escape innecesario se rechazan.
- `F09-26` — **la clave de idempotencia se reserva con un INSERT antes de ejecutar y se libera si la petición falla** — así, de dos peticiones iguales a la vez, una se ejecuta y la otra recibe `409` («sigue en curso»). Liberar la clave permite reintentar tras un error, que es para lo que existe la idempotencia. La reserva es una dependencia de la ruta que va siempre la última, después del guardián de permisos.
- `F09-26` — **el contrato fija el alfabeto de la clave** — `Idempotency-Key` pasa de «hasta 200» a 1–128 letras, cifras, `-` o `_`, lo mismo que exige el servidor. Contrato y tipos de la consola se regeneraron en la tarea.
- `F09-26` — **el asiento `campaign.launch` se escribe después de arrancar el workflow** — lleva el identificador del workflow. Si Temporal falla, la API responde con error y el asiento de la mutación no se escribe, porque no hubo lanzamiento.
- `F09-04` — **los permisos salen de un inventario de accesos recorrido desde el punto de entrada de cada contenedor, no de `log_statement=all`** — la tarea proponía las dos fuentes. Recorrimos el grafo de importaciones de cada servicio y extrajimos las sentencias SQL que llevan sus módulos. Un registro de sentencias solo ve lo que ejecutó la suite, y un camino sin test se habría quedado sin permiso en producción. La matriz del test (`db_access_matrix.yaml`) se escribió a mano desde ese inventario y las invariantes del producto, no copiando los `GRANT`.
- `F09-04` — **la migración es la 0033 y no la 0029** — la 0029 ya existía cuando llegamos. Se generó una vez desde el inventario, y lo que se commitea y revisa es el SQL.
- `F09-04` — **el inventario da más de lo que el producto permite, y se recorta a mano** — la API alcanza el código del evaluador, pero solo el worker de campañas escribe veredictos (F05-04). Del gateway quitamos lo que no usa ninguna de sus herramientas: el diario de consultas y la lectura del diario completo (SEC-051).
- `F09-04` — **`argos_ai` se conserva y hereda `svc_ai_gateway`** — los tests de la barrera de la Fase 06 lo usan por su nombre. Pierde el `SELECT` sobre todas las tablas que tenía, y la barrera se ajustó a lo que el gateway lee de verdad (veredictos y hallazgos). Añadimos un test de que no lee campañas, sujetos sintéticos ni la tabla de idempotencia. Comprobamos antes que ningún código del gateway lee `campaigns`.
- `F09-04` — **`refresh_catalog()` pasa a `SECURITY DEFINER` con `search_path` fijo** — refrescar una vista materializada solo lo puede hacer su dueño. Así las tres funciones que la llaman (API, gateway e inventario) no necesitan ser dueñas de nada.
- `F09-04` — **fuera el `LOAD 'age'` de cada sesión del grafo** — solo lo puede ejecutar un superusuario, y AGE ya se carga al arrancar (`shared_preload_libraries`). Lo comprobamos con un usuario miembro de `svc_ai_gateway` que lee el grafo sin él.
- `F09-04` — **un usuario de inicio de sesión fijo por servicio (`login_<servicio>`) hasta F09-05** — con contraseña aleatoria por entorno (`tools/dev_db_users.py`), escrita en un fichero ignorado por git, montada como secreto y guardada en Vault KV (`argos/database/<servicio>`). El servicio la lee de `ARGOS_DATABASE_PASSWORD_FILE` y no de Vault, porque el gateway de IA no alcanza Vault por diseño de su red: un solo mecanismo para todos. La contraseña nunca aparece en el compose. Además, `DATABASE_URL` deja de salir en el `repr` de la configuración, porque ahora la lleva dentro.
- `F09-04` — **SCRAM para toda conexión por red, también desde el host; confianza solo en el socket del contenedor** — no hay forma fiable de distinguir el host de los servicios: los dos llegan por la red de Docker. El superusuario tiene una contraseña de desarrollo (`dev-only-postgres`) que el `Makefile` exporta como `PGPASSWORD`, igual que `.env.example` y el `conftest` de los tests. El `pg_hba.conf` se monta con `hba_file` porque los volúmenes ya creados conservan el suyo con `trust`.
- `F09-04` — **cada contenedor se comprueba en vivo** — el test entra en los siete contenedores que usan la base y pregunta `current_user`: tiene que ser su usuario y no superusuario. Otro test comprueba que sin contraseña no se entra.
- `F09-03` — **el perfil seccomp de evidencia es una lista permitida realista, no la del documento de fase** — la del documento tiene unas 40 llamadas (y repite `ioctl`); un proceso Python con red, TLS, hilos y el núcleo en Rust de Temporal necesita bastantes más, y con esa lista el servicio no arrancaría. Escribimos 198 llamadas, todas permitidas también por el perfil por defecto de Docker, y ninguna de las que abren el host (`ptrace`, `mount`, módulos, `bpf`, espacios de nombres), lo que comprueba un test. Antes de darlo por bueno lo aplicamos en el compose a los dos servicios de evidencia y pasaron sus tests, los de contenedores y la demo.
- `F09-03` — **el resto de servicios usa el seccomp por defecto de Docker sin declararlo** — Docker lo aplica siempre que no se diga `unconfined`; el test del compose prohíbe `unconfined` en vez de exigir una línea que no cambia nada.
- `F09-03` — **la prueba en vivo mira `CapBnd`, `NoNewPrivs` y el montaje de la raíz, no `id -u` y escribir en `/`** — con las imágenes ya en `USER 10001`, esas dos comprobaciones pasaban antes de tocar el compose: un proceso sin root no tiene capacidades efectivas ni escribe en `/`. Las que añade la postura son el conjunto límite de capacidades vacío, la imposibilidad de ganar privilegios y la raíz montada `ro`, y esas sí fallaban antes.
- `F09-03` — **se quita `bash` de las imágenes y se deja `sh`** — «sin shell de más» sin romper la base Debian, que usa `sh`. Las comprobaciones de salud ya usan Python en forma exec. La imagen sin shell (distroless) queda para cuando se construya la del appliance.
- `F09-03` — **las imágenes de terceros van en una lista de excepciones con su motivo** — bases de datos, Vault, Keycloak, Temporal, observabilidad, dobles de desarrollo (TSA, EDC) y fuentes simuladas del cliente deciden su propio usuario; forzarles la postura sería probar otro producto. En el appliance las sustituye k3s con Kyverno (F09-92).
- `F09-31` — **las opciones de un enlace entre bases de datos (`options`) salen en claro** — la detección de flujos lee el host de `pg_foreign_server.srvoptions` y de `sys.servers.data_source`. Son configuración del propio sistema, no datos del cliente, y las credenciales de un enlace viven en `pg_user_mappings`, que no se lee. Lo destapó el `make check`: sin ellas, los flujos `engine_catalog` desaparecían de la verdad terreno de la Fase 03.
- `F09-31` — **la campaña anuncia que espera una compuerta solo cuando la solicitud ya está guardada** — el workflow ponía `awaiting:start` antes de ejecutar `request_approval`, y quien aprobaba en ese hueco no encontraba la solicitud. Lo vimos en el `make check` con la máquina cargada, en dos tests del workflow y antes en la demo. Se corrige en el workflow, porque la consola aprueba en cuanto ve ese estado.
- `F09-31` — **`check_config` se limita por las fuentes que lee, no solo por las columnas** — la tarea pedía ambas cosas y las aplicamos las dos: una sentencia declarada solo puede leer vistas de catálogo y configuración de su dialecto (comprobado con sqlglot, en el conector y en el lint), y de lo que devuelve solo salen en claro las columnas que nombran un ajuste o una identidad del sistema. Antes de fijar la lista comprobamos las tres sentencias declaradas de la biblioteca y las consultas nombradas de los conectores: todas pasan sin cambios.
- `F09-31` — **la comprobación de fuentes va detrás del validador de solo lectura** — el arnés de escrituras espera que una sentencia de escritura se rechace como violación de solo lectura y quede en el diario como rechazada. Si la comprobación de fuentes fuera antes, esas sentencias se rechazarían por otro motivo y el arnés dejaría de medir lo que mide.
- `F09-31` — **los identificadores se entrecomillan en vez de filtrarse por una lista de caracteres** — el entrecomillado del dialecto (SQLAlchemy) hace que el nombre sea solo un nombre, sea cual sea su texto; se siguen rechazando los vacíos, los de más de 128 caracteres y los que llevan caracteres de control. El objetivo `esquema.tabla` se parte por el primer punto porque un punto en el nombre de una tabla es mucho más frecuente que en el de un esquema.
- `F09-31` — **no metemos el driver ODBC 18 de Microsoft en la imagen** — la tarea lo daba por hecho, pero instalarlo exige aceptar su licencia (EULA) para una imagen que se entrega a clientes, y esa aceptación no es una decisión técnica nuestra. El código ya reconoce `pyodbc` con TLS verificado; hasta que la dirección decida, SQL Server funciona con `pymssql` y `allow_insecure` declarado, que es como está la fuente simulada. Queda como pendiente.
- `F09-31` — **DICOM con TLS sigue la convención de LDAP (`ca_file`)** — un único nombre de opción para la CA de un sistema en todos los conectores. La fuente simulada (Orthanc) escucha sin TLS y lo declara con `allow_insecure`, como las demás fuentes de desarrollo.
- `F09-31` — **los nombres del informe van en *code span*, sin escapar además a entidades HTML** — dentro de un *code span* CommonMark no interpreta ni Markdown ni HTML, así que `<img …>` se ve y no se ejecuta. Escapar también a entidades haría que un renderizador correcto mostrara `&lt;` literal.
- `F09-30` — **la excepción de destinos privados de los webhooks es configuración de la instalación, no del que suscribe** — el ITSM de un hospital suele estar en su red privada, así que prohibirlo sin más dejaría la integración inservible. Quien instala el appliance escribe esos nombres o redes en `ARGOS_WEBHOOK_ALLOWED_TARGETS`; un `platform_admin` desde la API no puede abrir la puerta por su cuenta.
- `F09-30` — **el destino se comprueba al suscribir y antes de cada entrega, sin fijar la IP en la conexión** — fijar la dirección resuelta en la conexión HTTPS exige forzar el SNI y la verificación del certificado a mano en httpx. La doble comprobación cierra el caso normal (un nombre que cambia de destino después de aceptado). El hueco que queda es un cambio de DNS entre la última resolución y la conexión (*DNS rebinding*), y queda anotado en el documento del módulo.
- `F09-30` — **la cookie de refresco pasa a ser de sesión y su ruta a `/api/v1/auth`** — sin `Max-Age` muere con el navegador, que es lo que pide un puesto compartido; el realm sigue limitando cuánto vale el refresco. La ruta se amplía porque el cierre de sesión necesita leer la cookie para revocarla, y `/api/v1/auth` solo contiene `session`, `refresh` y `logout`.
- `F09-30` — **`logout` es una ruta abierta, como el refresco** — lo que prueba quién es la persona en ese momento es la cookie que se revoca, no un token de acceso que puede haber caducado ya. La matriz de autorización lo recoge en su lista de rutas abiertas.
- `F09-30` — **CSP estricta (`default-src 'self'`) sin excepciones para la consola** — antes de fijarla comprobamos que el `index.html` construido solo carga un script y una hoja de estilos propios, sin nada en línea, y que el único salto a otro origen es la navegación a Keycloak, que la CSP no restringe. La única excepción es `/api/v1/docs` de desarrollo, que carga de una CDN.
- `F09-30` — **la bandeja de webhooks guarda la clase de error, no su texto** — el texto de una excepción de red puede traer nombres internos o lo que el otro extremo quiera contestar. Cuatro clases (`destination_refused`, `timeout`, `connection`, `transport`) bastan para diagnosticar, y las filas antiguas con texto se muestran como `transport`.
- `F09-29` — **la rebaja de una columna con contexto de categoría especial va siempre a una persona** — el «contexto» es el diccionario determinista aplicado a la propia columna, a su tabla y a sus columnas hermanas. Las columnas de la zona gris no casan por su nombre (si casaran, ya estarían clasificadas), así que el indicio útil está en la tabla y en las hermanas. Además, los lotes pasan a ser de una tabla: un nombre hostil de otra tabla ya no comparte prompt con la columna.
- `F09-29` — **la cuota por persona es el 20 % de la del servicio, en memoria** — con los 3.000.000 tokens diarios del asistente, son unas 25 preguntas completas por persona y día, y cinco personas llenan la cuota. Guardarla en la base exigía una columna nueva en `ai_usage` (una migración) para un límite que se afina con uso real, así que queda en memoria y anotado.
- `F09-29` — **el gateway exige `person` en `/v1/assistant/ask`** — sin él, la cuota volvía a ser de todos. Solo lo llama la API, que ya autentica a quien pregunta, así que no rompe a ningún cliente.
- `F09-29` — **5 s de `statement_timeout` y 4 herramientas a la vez** — las herramientas son recuentos, una cobertura y una página del grafo: en la demo responden en milisegundos, así que 5 s solo corta lo que no debería ocurrir. Las cuatro plazas son de proceso y compartidas entre preguntas.
- `F09-29` — **`query_graph` deja de ofrecer `system_kind` en vez de resolverlo** — resolverlo pedía una consulta más de los sistemas por tipo, dentro de una herramienta que debe ser barata, y ningún conjunto dorado lo necesitaba.
- `F09-29` — **el contenedor del gateway se conecta con las herramientas reales y `EMBEDDING_MODEL` configurable** — sin modelo sigue respondiendo 503, pero ahora por la razón correcta. El servidor de desarrollo solo sirve el modelo de chat, lo que queda anotado para F06-05.
- `F09-28` — **los identificadores se reconocen con límites solo de dígito, no de «letra o dígito» como proponía la tarea** — SEC-032 señala expresamente un DNI «pegado a `_` o a letras», y con límites de letra `columna12345678Zfin` seguiría llegando al modelo. Quitar ese límite no destroza códigos inocentes porque la decisión sigue siendo del validador de ARG-024, que se aplica al valor sin separadores. Lo comprobamos con un código de pedido con forma de DNI y letra equivocada, que queda intacto.
- `F09-28` — **las afirmaciones de conformidad son formas verbales, no la raíz `cumpl\w*` que proponía la tarea** — con la raíz, «el cumplimiento del artículo 32 exige cifrado» (explicar la norma, lo que hace el asistente a diario) se rechazaría. Además, las formas de «cumplir» tras «que» no cuentan: al ampliar el conjunto dorado vimos que dos retos de la biblioteca (`coh-treatment-legal-basis` y `coh-ai-risk-class-declared`) describen su criterio como «los tratamientos que incumplen la forma», y el generador de retos dejaba de pasar (0,67 en `generate`). El coste queda anotado: una afirmación en oración de relativo se escapa.
- `F09-28` — **el texto se lee dos veces, con los caracteres de ancho cero quitados y como espacios** — el carácter puede separar dos palabras («es​conforme») o esconderse dentro de una («cum​ple»); con una sola lectura, uno de los dos casos pasa.
- `F09-28` — **una cantidad escrita en letra se rechaza siempre en un dictamen, salvo «un», «una» y «uno»** — no se puede contrastar con los datos, así que aceptarla sería abrir la puerta que cierra el verificador. Los tres artículos quedan fuera porque son artículos mucho más a menudo que números.
- `F09-28` — **el asistente puede dar cifras de la propia pregunta además de las de sus herramientas** — si el usuario pregunta «¿hay más de 5 hallazgos?», responder «no hay más de 5» no inventa nada. Las cifras del texto de los fragmentos recuperados (por ejemplo, «72 horas») también cuentan como respaldo.
- `F09-28` — **un conjunto dorado propio, `guardrails`, con umbral 1,00** — los casos hostiles del depurador y de la salida no pasan por un modelo, así que no encajaban en ningún conjunto existente. Los de cifras sí se añadieron a `reports`, que ya pasa por el verificador. Como `make ai-eval` forma parte de `make check`, cualquier regresión rompe la verificación.
- `F09-27` — **el plazo de un derecho lo miden las fechas que declara el cliente, obligatorias** — la solicitud que recibió y la respuesta que dio, no futuras y en orden. Antes se medía entre dos clics de la consola, y el cliente podía confirmarlos con un minuto de diferencia aunque tardara 40 días. Las fechas van en una tabla propia (`synthetic_exercises`), una fila por derecho y sin cambios posibles. Esto cierra también el pendiente de «varios derechos en una fila». Si hay varias respuestas, cuenta la más lenta.
- `F09-27` — **una respuesta que nunca llega no se puede confirmar, y el reto queda `inconclusive`** — exigimos las dos fechas para no medir contra la hora de la consulta, que haría variar el veredicto según cuándo se ejecute la campaña. Queda anotado como límite: un cliente que no responde no produce un `non_compliant`.
- `F09-27` — **un sujeto sintético siempre pertenece a una campaña** — sin campaña escapaba a la comprobación de la reversión. La restricción entra como `CHECK ... NOT VALID`: vale para todo sujeto nuevo sin tocar las filas antiguas de la base de desarrollo. Consecuencia: la demo y la prueba de la fase 5 crean primero la campaña y registran el sujeto en ella, y cada campaña usa su propia semilla (el id del sujeto sale de ella). Comprobamos antes que un veredicto no incluye los parámetros de la sonda, así que dos campañas con sujetos distintos y los mismos recuentos siguen dando el mismo hash.
- `F09-27` — **la precondición del sujeto la comprueba el compilador** — donde el cliente no confirmó la inyección, la unidad sale como no verificable con su motivo, en vez de ejecutarse contra un sistema donde no hay nada que medir.
- `F09-27` — **la campaña espera a la reversión y la comprueba antes de sellar** — el workflow pasa a `awaiting:revert` hasta que el cliente confirma cada reversión. Entonces busca los marcadores del sujeto con la sonda `count` del conector, en las columnas del punto clasificadas como identificador oficial, contacto o dato financiero (DNI, correo e IBAN del sujeto). Mientras falta alguna confirmación consulta cada 5 s sin tocar al cliente; si el sujeto sigue ahí, vuelve a mirar cada 5 minutos para no cargar la fuente. Un punto que no se puede sondear (otro conector o sin columnas de esas categorías) bloquea el sello: preferimos una campaña que no cierra a un sello que certifica una reversión que nadie ha visto. `seal_campaign` repite la comprobación, así que no se puede sellar saltándose el workflow.
- `F09-27` — **SHACL se evalúa sobre el grafo congelado con la instantánea, no sobre la tabla de nodos** — la tabla de la instantánea no guarda las propiedades ni las relaciones que validan las formas (base jurídica, `DECLARED_IN`, clase de riesgo). Guardamos el grafo exportado como N-Triples ordenados, con su SHA-256, en una tabla inmutable junto a la instantánea, y el hash se comprueba al leerlo. Se toma justo después de la instantánea y no en la misma transacción; queda anotado como límite.
- `F09-27` — **la subsanación mide sobre una instantánea nueva y se sella** — con la instantánea de la campaña original, un hallazgo del inventario (`coh-unclassified-columns`) no podía cerrarse nunca. Las referencias a la instantánea dentro de cada unidad guardada se reescriben a la nueva, y la campaña de subsanación se sella como cualquier otra.
- `F09-25` — **un cliente conocido de OPA puede listar las políticas (`GET /v1/policies`), lo que la auditoría del 2026-09-18 (M7) prohibía** — M7 cerró toda lectura de políticas. Al comprobar lo que OPA ejecuta, reabrimos solo el listado y solo con token: las reglas que devuelve (la biblioteca y `authz.rego`) ya están en el repositorio, que es público. Siguen cerrados lo que sí identifica a un cliente (`/v1/data/opa_clients`, con las huellas de los tokens), la lectura de una política suelta y cargar o sustituir políticas. Lo detectó `make check`: el test de M7 que lo prohibía falló, y lo cambiamos por uno que prueba justo esa frontera.
- `F09-25` — **si el contenido no es el firmado, la campaña se para; no sigue con el bueno** — la tarea pedía que un `.rego` cambiado «no altere el veredicto». Parar antes de fijar versiones es más estricto y deja constancia: una biblioteca manipulada en el appliance es un incidente, no algo que se deba absorber en silencio.
- `F09-25` — **anti-retroceso por semver con escape explícito** — `load_bundle` rechaza una versión anterior a la más reciente cargada salvo `allow_rollback=True`. La misma versión con otro contenido ya la rechazaba `store_version`. El escape existe porque retirar una versión defectuosa es una operación legítima, pero tiene que pedirse a propósito.
- `F09-25` — **tope de 200 MB descomprimidos por bundle** — la biblioteca firmada ocupa unos pocos megabytes. El tope deja margen de sobra para crecer y corta un tar.gz hostil de un soporte extraíble antes de agotar la memoria. El manifiesto tiene que ir primero para verificar la firma antes de leer nada más.
- `F09-25` — **tests y demo publican la biblioteca firmada, en vez de guardar el grafo sin firmar** — con la comprobación en ejecución, una campaña con contenido sin bundle ya no arranca. Probar el camino real (firma con `argos-content` de Vault de desarrollo) es además lo que queremos que cubran los tests. Comprobamos que el grafo del bundle es isomorfo al de `library_graph()`, así que la aplicabilidad no cambia.
- `F09-24` — **la separación de deberes se comprueba por persona en el dominio, además de por rol en la API** — quien crea una campaña (o pide una subsanación) no aprueba sus compuertas, y quien autoriza un punto de inyección no lo confirma. La regla vive en el motor y no depende de cómo asigne los roles el realm del cliente ni de la federación.
- `F09-24` — **un token con `campaign_manager` y `dpo_reviewer` a la vez se rechaza en toda ruta** — el par incompatible se declara en `permissions.yaml` (`_incompatible_roles`), a la vista del cliente como el resto de la matriz. Comprobamos antes que ningún usuario de desarrollo tiene los dos roles. Rechazar el token completo y no solo las rutas de aprobar hace visible el error de configuración del realm desde la primera petición.
- `F09-24` — **aceptar un riesgo tiene fecha futura y como mucho 12 meses** (`RISK_ACCEPTANCE_MAX_DAYS = 365`) — sin tope, `9999-12-31` silenciaba un hallazgo crítico para siempre. Doce meses coinciden con el ciclo anual de revisión que espera un auditor ENS/ISO. Se comprueba en el dominio y la API lo devuelve como 422.
- `F09-23` — **el evaluador solo escribe veredictos del plan guardado** — la unidad que llega en el payload de Temporal se compara con la de `argos.campaign_units` y, si no coincide o no existe, no hay veredicto. Además, la campaña tiene que estar en curso y con sus compuertas aprobadas. Quien alcance Temporal puede lanzar un workflow, pero no puede meter en el sello una unidad que nadie planificó (SEC-007).
- `F09-23` — **el muestreo exige siempre doble control, lo declare o no el reto** — el compilador deriva la compuerta `sampling` de que haya muestreo o sonda de muestra, en vez de fiarse del campo `approval_required`. No se tocó `ret-table-retention.yaml`: con la derivación, el campo que le faltaba deja de importar.
- `F09-23` — **la biblioteca se comprueba también al cargar, no solo en el CI** — las reglas que no necesitan contexto (`intrinsic_errors`: muestra sin aprobación, evidencia declarada en el `input_map`) se aplican en `load_library`. Un reto que se salte el CI no llega a ejecutarse.
- `F09-23` — **la evidencia de OPA la trae siempre la sonda** — un reto no puede declarar `result`, `out_of_term`, `max_age_days` ni `documented_exceptions`, y en ejecución se descartan aunque lleguen. Las referencias `$client` del `input_map` se resuelven como las de la sonda. Comprobamos que resolver `treatment` no cambia los veredictos de la fase 5, porque la regla que se aplica cuenta los registros fuera de plazo.
- `F09-23` — **sello versión 2, con la versión 1 aún verificable** — el sello cubre ahora el plan (cada unidad con su criterio resuelto) y las aprobaciones, solo se sella una campaña en curso y es válido si es el único anclaje `campaign.seal` de la campaña. Las campañas ya selladas con la versión 1 se verifican con la versión 1, que el anclaje del diario identifica: nada sellado antes deja de verificar sin explicación.
- `F09-23` — **una campaña sellada no admite más veredictos ni cambios de sello, por disparador de la base** — la regla vive en la base, así que no importa el rol ni el proceso que lo intente.
- `F09-23` — **la subsanación pasa por las compuertas de cualquier campaña y consulta las aprobaciones en vez de esperar una señal** — la campaña de subsanación se crea dentro del workflow y la API no conoce su identificador para señalarla. El workflow consulta las aprobaciones registradas cada 5 s. La API ya no falla al señalar una campaña que no tiene workflow propio.
- `F09-23` — **un fallo de OPA se reintenta y no se sella como `inconclusive`** — una caída o un token caducado no son una respuesta sobre el sistema del cliente.
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
