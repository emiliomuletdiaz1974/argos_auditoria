---
id: MOD-argos-challenge-engine
kind: module
title: Motor de retos y campañas (argos-challenge-engine)
module: argos-challenge-engine
phases: ["01"]
version: 0.1.0-alpha
commit: pendiente
date: 2026-09-18
status: current
confidentiality: client
---

# Motor de retos y campañas (argos-challenge-engine)

## 1. Propósito

Servicio que orquestará las campañas de verificación (retos, sondas, criterios y evidencias) sobre Temporal. En su estado actual contiene la **base** que se construyó en la Fase 01 (ARG-007): el worker, la política de reintentos y el patrón de workflows y actividades que usará el motor completo de la Fase 05 (ARG-041…050).

## 2. Alcance y límites

- **Hoy:** un worker de Temporal con un workflow de humo (`SmokeCampaign`) que ejecuta una sonda simulada y anota el resultado en el diario de auditoría.
- **No incluye todavía:** biblioteca de retos, compilación de selectores, campañas reales ni sellado de evidencia. Este documento está en estado `draft` y se completa en la Fase 05.

## 3. Arquitectura

- **Workflows** (`workflows.py`): deterministas y **sin entrada/salida**, para que Temporal pueda reejecutarlos desde su historial.
- **Actividades** (`activities.py`): toda la entrada/salida (sondas y escritura en el diario) vive aquí, con reintentos y límite de tiempo.
- **Worker** (`worker.py`): registra workflows y actividades en la cola `argos-campaigns`.

Dependencias: `argos-common` (configuración, registro y diario) y el SDK de Temporal.

### Lenguaje de retos (ARG-041)

Un reto es un documento YAML con seis bloques obligatorios (`objective`, `selector`, `probe`, `criterion`, `evidence` y `severity`) más `id`, `version` y `title`; opcionalmente `sampling`, `approval_required`, `preconditions` y `estimated_cost`.
- **El esquema manda:** `library/challenges/schema/challenge.schema.json` (JSON Schema 2020-12). Lo que no encaja no compila.
- **Se puede escribir en castellano:** la capa `argos_challenges.library.translation` traduce claves y valores (`objetivo`, `sonda`, `criterio`, `severidad: alta`…) al núcleo en inglés con una tabla cerrada y biyectiva. Una clave o un valor fuera de la tabla es un error, nunca algo que se ignore, y el núcleo nunca ve castellano (ADR-0007, decisión de F05-00).
- **Parámetros tipados, nunca texto interpolado:** los valores que dependen del nodo, del cliente, de la campaña o del sujeto sintético se declaran como `{$node: …}`, `{$client: …}`, `{$campaign: …}` y `{$subject: …}`, y viajan como parámetros de la sonda. El esquema rechaza cualquier `{{…}}`.
- **Sondas:** las cuatro del SDK (`scan_schema`, `count`, `sample`, `check_config`) más dos internas de solo lectura sobre datos de ARGOS: `shacl` e `inventory_query`.
- **Reglas del producto** (`lint_challenge`), que un esquema no puede expresar:
  - una sonda `sample` exige aprobación y `hashed_sample` solo se captura con ella;
  - la obligación existe y cita al reto;
  - la clase de activo existe;
  - el paquete Rego del criterio está en la biblioteca;
  - el fichero se llama como el reto.
- **Retos patrón:** `ret-table-retention` (criterio delegado en OPA, escrito en castellano) y `sec-encryption-at-rest` (umbral, escrito en inglés).
- **Comprobación:** `make challenge-lint`, también en el job `verify` del CI.

### Biblioteca de retos (ARG-050)

- **Organización:** `library/challenges/<familia>/<id>.yaml`, con las familias del catálogo (`acc`, `brc`, `coh`, `doc`, `ds`, `dsr`, `ret` y `sec`) y subcarpetas por vertical.
- **Catálogo generado:** `tools/challenge_catalog.py` lo escribe desde los retos y `--check` (`make challenge-catalog`, también en CI) comprueba que está al día. Ya no se edita a mano, así que la biblioteca y la matriz de trazabilidad de la ontología no pueden divergir.
  - El tipo de evidencia sale de la sonda: configuración para `check_config` y `scan_schema`, resultado de consulta para las demás.
  - Un id que las poblaciones citan pero cuyo reto aún no existe queda con `draft: true`: hoy, 27 entradas de las que 25 están reservadas.
- **Archivo por versión:** al publicar, `tools/ontology_publish.py build` congela los retos en `library/challenges/archive/<versión>/` y los empaqueta en el bundle firmado. Una versión archivada no cambia, y es la que verifica la subsanación de un hallazgo (ARG-049).

### Sujeto sintético (ADR-0008)

El reto estrella del producto, el borrado efectivo, necesita un interesado de prueba. ARGOS **genera y registra**; el **cliente inyecta y ejerce los derechos** por sus propios canales. Ningún paquete del producto escribe en un sistema del cliente: el solo-lectura por construcción sigue intacto.
- **Identidades marcadas y reproducibles:** con la misma semilla salen los mismos sujetos, id incluido. El DNI está en un rango que nunca se expide (99992001–99992999, por encima del que usan las fuentes simuladas), el IBAN lleva una entidad ficticia, el correo va a `example.invalid` y el nombre empieza por `SYN`. `is_synthetic` reconoce cualquiera de esas marcas.
- **Inventario auditado** (migración `0011`): `argos.synthetic_subjects` guarda solo los **hashes** de los valores; los valores en claro viajan únicamente en el paquete que recibe el cliente. `argos.synthetic_injections` guarda cada punto autorizado con su procedimiento de reversión.
- **Flujo con el cliente,** cada paso anotado en el diario:
  1. `register_subjects` (`synthetic.generate`);
  2. `authorize_injection`, que exige una persona y un procedimiento de reversión (`synthetic.authorize`);
  3. `confirm_injection`, `confirm_exercise` y `confirm_revert`, que confirma el cliente (`synthetic.injected`, `synthetic.exercised`, `synthetic.revert`).
- **Escritura única:** los triggers impiden cambiar una autorización o repetir una confirmación, y los sujetos son inmutables.
- **Sin confirmación no hay absolución:** un reto con `preconditions: [synthetic_subject_injected]` queda `inconclusive` mientras el cliente no confirme.
- **Reversión:** `pending_reversions` lista lo inyectado y no revertido; una campaña no se sella con sujetos sin revertir.
- **En la demostración:** `tools/demo_client_actions.py` hace de cliente con las credenciales de propietario de las fuentes simuladas: inyecta, suprime solo en la base clínica y deja el sujeto plantado en la réplica de facturación.

### Muestreo declarado (ARG-045)

Sobre poblaciones grandes el censo no es viable, y la honestidad exige dos cosas: calcular la muestra para la confianza declarada y **decidir sobre la cota superior** de incumplimiento, nunca sobre la estimación puntual.
- `sample_size(population, confidence, margin)` aplica la corrección por población finita, que es el estándar de auditoría.
- `wilson_upper(failures, sample, confidence)` da la cota superior del intervalo de Wilson; sin muestra devuelve 1,0, es decir, no absuelve.
- `required_sample_size(failures, target, confidence)` dice cuánta muestra haría falta para demostrarlo: es lo que acompaña a un veredicto **no demostrado**.
- `plan_sampling(unit, population)` decide censo (por debajo de 5000) o muestra, y **devuelve una unidad nueva**: la que recibe no cambia, porque el historial de Temporal puede haberla leído.
- Solo se usan operaciones IEEE correctamente redondeadas, para que el resultado sea idéntico en cualquier máquina.

### Evaluador determinista (ARG-046)

Es la frontera del producto hecha código: **el veredicto no lo decide nunca un modelo de lenguaje**, sino una de dos vías cerradas, un umbral declarado o el paquete Rego que cita el reto.
- `evaluate(unit, probe_result, opa_decision=None)` es una **función pura**: sin entrada/salida, sin reloj y sin identificadores. La actividad que la envuelve habla con OPA y escribe en la base.
- **Cuatro resultados:** `compliant`, `non_compliant`, `not_demonstrated` (la muestra no permite absolver, con la muestra que haría falta) e `inconclusive` (la sonda falló, la evidencia no responde o los valores no son comparables).
- **Operadores de una tabla cerrada**, sin `eval`. Comparar texto con número no lanza: da `inconclusive`.
- **Con muestreo**, la decisión se toma sobre la cota superior proyectada a la población, con seis decimales redondeados hacia arriba y en texto, para que los bytes del veredicto sean idénticos en cualquier máquina. Lo que la muestra ya demuestra incumplido no lo absuelve ninguna cota.
- El veredicto se serializa con la canonización del diario y lleva su SHA-256 (`Verdict.canonical()` y `Verdict.hash`), que es lo que sella la campaña y lo que compara la reejecución.

### Campañas, veredictos y compuertas (migración `0012`)

- **`argos.campaigns`** (ampliada desde la Fase 01) guarda lo que la campaña **fija**: instantánea y su hash, versión de ontología, versión y hash de la biblioteca, y la ejecución de aplicabilidad. Con eso, dos ejecuciones de la misma campaña son comparables. Estados: `planned` → `pinned` → `running` → `sealed`, o `failed`; nunca hacia atrás.
- **`argos.campaign_units`** guarda la unidad compilada entera. Es lo que vuelve a ejecutar la verificación de una subsanación, aunque la biblioteca avance.
- **`argos.verdicts`** tiene una fila por unidad (`UNIQUE (campaign_id, unit_id)`), con el veredicto canónico y su hash. Es **inmutable**: los triggers rechazan `UPDATE`, `DELETE` y `TRUNCATE`, y un `CHECK` limita el resultado a los cuatro valores.
- **`argos.approval_requests` y `argos.approvals`**, también de escritura única, sostienen las compuertas: pedir dos veces la misma compuerta conserva la primera petición, y el doble control cuenta personas distintas.
- `argos_challenges.store` es el **único** módulo que escribe veredictos (lo vigila el test arquitectónico) y cada escritura lleva su asiento en la misma transacción: `campaign.create`, `campaign.pin`, `approval.request`, `approval.grant` y `verdict.emit`.
- **Idempotencia:** `persist_verdict` inserta con `ON CONFLICT DO NOTHING`; si la actividad se reintenta, devuelve el veredicto que ya había y no anota un segundo asiento.

### Resolución sobre la instantánea y compilador (ARG-042)

- **`SnapshotSelectorResolver`** responde los mismos selectores que la API del inventario, pero leyendo las filas de la instantánea que fijó la campaña. Cumple el protocolo del resolutor de la Fase 04, así que la aplicabilidad se resuelve sobre la foto y no sobre el grafo vivo: es lo que hace comparables dos ejecuciones. Un test de integración comprueba que las nueve clases de activo dan exactamente los mismos nodos por las dos vías.
  - La instantánea guarda ahora también el `status` (migración `0013`), que necesita la clase de los sistemas de IA confirmados.
- **`compile_campaign`** convierte cada fila del plan en una **unidad de trabajo inerte**: sonda resuelta, criterio, evidencia, severidad, muestreo, precondiciones y `unit_id` estable. El workflow no interpreta nada, así que el DPO puede leer el plan tal como se va a ejecutar.
  - **Variante por conector:** el identificador sale del conector registrado del sistema (`rdbms.postgresql`, `rdbms.generic`, `files.smb`…). El motor concreto del conector SQL genérico vive en su secreto de Vault, por eso su identificador se queda genérico.
  - **Parámetros tipados:** `{$node: …}`, `{$client: …}`, `{$campaign: …}` y `{$subject: …}` se resuelven a valores aquí y viajan como parámetros; ningún valor del grafo se concatena en una consulta. Una referencia que falta es un error, no un valor vacío.
  - **Sin variante para el conector del sistema**, la unidad no desaparece: queda en `unverifiable` con su motivo.
  - Mismas entradas, mismas unidades y en el mismo orden.

### Actividades de sonda y evaluación (ARG-044)

Los workflows quedan deterministas y sin entrada/salida; todo lo que habla con un sistema del cliente, con OPA o con la base vive en `ChallengeActivities`.
- **`probe`** ejecuta la unidad:
  - las sondas de conector (`scan_schema`, `count`, `sample`, `check_config`) pasan por el SDK, con su asiento previo, su presupuesto de carga y la garantía de solo lectura;
  - las internas (`shacl` e `inventory_query`) leen lo que ARGOS ya sabe (la instantánea y el grafo) y no tocan ningún sistema del cliente; la consulta interna se elige de una **lista cerrada** por nombre, un reto no escribe la suya.
- **Errores con significado distinto:**
  - presupuesto agotado o cortacircuitos abierto **no son fallos**, son esperas: vuelven como reintentables;
  - una violación de solo lectura **no se reintenta**: congela la unidad y deja asiento `probe.readonly_violation`.
- **Minimización antes de devolver:** solo salen las claves que permite lo declarado en `evidence.capture`; ni valores, ni cadenas de conexión, ni nada sin declarar llega al historial del workflow.
- **`wait_window`** espera la ventana pactada del sistema con latido, sin fallar.
- **`evaluate`** consulta OPA si el criterio lo delega, llama al evaluador puro y persiste con `persist_verdict`: repetir la actividad no duplica veredictos.
- El worker registra estas actividades junto a las de humo (`campaign_activities()` las ata a la base, a Vault, a OPA y al bus). Con el bus conectado, sellar una campaña se **anuncia** en `argos.campaign.sealed`: el servicio de evidencia (F07-13) escucha y lleva la campaña hasta su credencial. La campaña no espera a nadie ni depende de que el servicio de evidencia exista.

### Ciclo de vida de los hallazgos (ARG-048)

Un hallazgo no es una línea de registro: es una **no conformidad con dueño, severidad y camino de salida** (migración `0014`).
- **Estados:** `open` → `in_remediation` → `pending_verification` → `closed_compliant`, o `reopened` si la reejecución no lo confirma. La vía excepcional es `risk_accepted`, una decisión documentada con caducidad, porque negar esa vía solo produce hallazgos eternamente abiertos que nadie mira.
- **Solo se cierra por verificación:** ni la consola ni el DPO pueden pasar directamente a cerrado; lo confirma el mismo reto reejecutado.
- **Deduplicación por huella** (reto y nodo), en una sola sentencia: campañas sucesivas no multiplican el hallazgo, suben su contador; desde tres campañas distintas, suben su severidad un nivel (`critical` ya no sube más).
- **Una reapertura no es una recurrencia:** es el mismo problema visto otra vez.
- **Aceptar el riesgo** exige justificación y fecha de caducidad, y la base lo impone con un `CHECK`. Al caducar, `expire_risk_acceptances` lo devuelve a `reopened` con asiento del sistema.
- Cada paso deja asiento (`finding.open`, `finding.recur`, `finding.transition`) y la apertura publica `challenge.finding_opened.v1` para la consola y los webhooks.

### Workflow de campaña y sello (ARG-043)

Una campaña es un proceso de días con personas dentro: sobrevive a reinicios, se detiene en las compuertas, cede el paso cuando un sistema del cliente abre su cortacircuitos y termina sellando lo que midió.
- **`CampaignWorkflow`:** prepara (instantánea, versión de ontología, versión y hash de la biblioteca, aplicabilidad sobre la instantánea y compilación), pide la compuerta `start`, pide `sampling` si alguna unidad la necesita, lanza un hijo `SystemRun` por sistema y sella.
- **`SystemRun`** recorre las unidades de su sistema en serie: espera de ventana, sonda y evaluación. El presupuesto de carga ya marca el ritmo.
- **Señales y consulta:** `approve(gate)`, `circuit_open(system_id)`, `circuit_closed(system_id)` y `progress`. Un sistema pausado **espera**, no gira en vacío.
- **Sin entrada/salida en el workflow:** todo pasa por actividades, así que Temporal puede reejecutar su historial.
- **Sello (`argos_challenges.seal`):** un SHA-256 canónico sobre los veredictos, la instantánea, la versión de ontología y la de la biblioteca; se guarda en la campaña y se ancla en el diario (`campaign.seal`). `verify_seal` lo recalcula desde las tablas y comprueba el asiento; tocar un veredicto lo rompe.
  - Una campaña **no se sella** con sujetos sintéticos inyectados y sin revertir.
  - La Fase 07 lo envolverá con Merkle y firma sin cambiar lo que se sella.
- **Parámetros del cliente:** el calendario de conservación y sus columnas de referencia son del cliente; viven junto a los datos de OPA y el compilador resuelve `{$client: …}` desde ahí.

### API de campañas y puntos de control (ARG-047)

El reparto del pliego es taxativo: **ARGOS ejecuta y evidencia, el cliente aprueba**. Esta API es donde ocurre.
- **Roles del realm:** `campaign_manager` planifica y lanza; `dpo_reviewer` aprueba compuertas, autoriza la inyección de un sujeto sintético y mueve un hallazgo; cualquier rol puede leer. Sin token, 401; con token sin rol, 403.
- **Compuertas:** `GET /campaigns/{id}/gates` muestra qué se aprueba y cuántas aprobaciones faltan; `POST …/approve` registra la del usuario, y al alcanzar las necesarias envía la señal al workflow. `sampling` exige **doble control**: dos personas distintas; la misma no cuenta dos veces.
- **Sujeto sintético:** autorización del punto de inyección (DPO) y confirmaciones del cliente (inyección, ejercicio del derecho y reversión).
- **Hallazgos:** `POST /findings/{id}/transition`, con la máquina de estados; una transición ilegal responde 409.
- **Lectura:** estado de la campaña con `seal_verified` recalculado, veredictos y hallazgos.
- Cada acción entra en el diario con el usuario que la hizo.
- Desde F08-17 estas rutas son las de la API única (`argos_api`, `127.0.0.1:8000`): este módulo ya no expone HTTP.

### Reejecución de subsanación (ARG-049)

El cierre de un hallazgo no lo declara el cliente: lo confirma **el mismo reto que lo abrió**, reejecutado sobre el mismo nodo.
- `RemediationRun` toma los hallazgos en `pending_verification`, reejecuta **la unidad guardada con el veredicto** y transiciona según el resultado: `closed_compliant` si cumple, `reopened` si no. Un `not_demonstrated` o un `inconclusive` dejan el hallazgo donde estaba, con su motivo.
- Como la unidad viaja con el veredicto, la subsanación se mide con **la versión del reto que midió el problema**, aunque la biblioteca haya avanzado.
- La reejecución corre en su **propia campaña** de subsanación, que hereda la instantánea y las versiones de la original: así el veredicto nuevo no pisa al que abrió el hallazgo.
- **Una reapertura no cuenta como recurrencia:** las unidades de subsanación van marcadas y no suben el contador ni la severidad.
- No se relanza la campaña entera: vuelven exactamente las unidades no conformes. Es lo que hace creíble que la segunda credencial cueste una fracción.
- Se lanza con `POST /remediation` (rol `campaign_manager`), con o sin campaña concreta.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Constante | `TASK_QUEUE = "argos-campaigns"` | Cola de tareas del dominio de campañas |
| Función | `create_worker(client, task_queue)` | Construye el worker con workflows y actividades registrados |
| Constante | `RETRY_POLICY` | 3 intentos, retroceso ×2 desde 200 ms |
| Workflow | `SmokeCampaign` | Workflow de humo del patrón |
| Actividades | `smoke_probe(system)`, `record_in_journal(action, payload)` | Sonda simulada y asiento en el diario |
| Proceso | `python -m argos_challenges.worker` | Arranque del worker |
| Fichero | `library/challenges/schema/challenge.schema.json` | Esquema del DSL de retos |
| Funciones | `parse_challenge(document, source=None)`, `load_challenge_file(path)`, `library_challenges(dir)`, `lint_challenge(spec, context, path=None)`, `load_schema()`; tipos `ChallengeSpec`, `LintContext`, `ChallengeError` | Modelo y validación de retos |
| Funciones | `read_challenge(text)`, `to_internal(doc)`, `to_editorial(doc)`; tablas `CHALLENGE_KEYS`, `CHALLENGE_VALUES`; `TranslationError` | Capa de traducción en castellano |
| Herramienta | `tools/challenge_lint.py [--library DIR]` y `make challenge-lint` | Valida la biblioteca; código 1 si hay errores |
| Tabla | `argos.findings` (migración `0014`) | Hallazgos con huella única, contador, severidad y caducidad del riesgo aceptado |
| Funciones | `open_or_recur`, `transition`, `expire_risk_acceptances`, `fingerprint`, `escalate`, `announce`; `FindingError`, `STATUSES`, `TRANSITIONS` | Ciclo de vida de los hallazgos |
| Asientos y evento | `finding.open`, `finding.recur`, `finding.transition`; `challenge.finding_opened.v1` en `argos.challenge.finding_opened` | Trazabilidad y aviso de hallazgos |
| Lecturas | `store.list_campaigns`, `store.list_verdicts`, `store.campaign_gates`, `store.campaign_plan`, `store.running_campaigns`; `DOUBLE_CONTROL_GATES = {"sampling"}` | Lo que sirve la API única |
| Puente | `bridge.on_circuit_open(running, signal)`, `bridge.SUBJECT`/`DURABLE`/`SIGNAL` | El cortacircuitos del conector pausa la campaña |
| Rutas | `POST /campaigns`, `POST /campaigns/{id}/launch`, `GET /campaigns/{id}`, `/verdicts`, `/findings`, `/gates`, `POST /campaigns/{id}/gates/{gate}/approve`, `POST /campaigns/{id}/synthetic/authorize`, `POST /synthetic/{id}/confirm-injection\|confirm-exercise\|confirm-revert`, `POST /findings/{id}/transition` | Puntos de control humanos |
| Workflows | `RemediationRun` (actividades `start_remediation` y `transition_finding`); ruta `POST /remediation` | Verificación de subsanaciones |
| Workflows | `CampaignWorkflow` (señales `approve`, `circuit_open`, `circuit_closed`; consulta `progress`) y `SystemRun` | Orquestación de la campaña |
| Funciones | `seal_payload`, `compute_seal`, `seal_campaign`, `verify_seal`, `announce_seal`; `SealError`; evento `challenge.campaign_sealed.v1`; asiento `campaign.seal` | Sello de campaña |
| Funciones | `client_parameters()`, `client_data()`; `library_fingerprint()` | Parámetros del cliente y huella de la biblioteca |
| Clase | `ChallengeActivities(dsn, secrets, opa_url, bus)` con las actividades `probe`, `wait_window` y `evaluate`; `campaign_activities(cfg)` | Actividades de campaña |
| Funciones | `minimise(data, capture)`, `probe_spec(unit)`; tablas `CAPTURE_KEYS` e `INVENTORY_QUERIES` | Minimización y sondas internas |
| Asiento | `probe.readonly_violation` | Intento de escritura detectado en un conector |
| Clase | `SnapshotSelectorResolver(dsn, snapshot_id)` con `resolve(selector)` y `nodes`; función `matches(node, selector, system_ids)` | Resolución de selectores sobre la instantánea |
| Funciones | `compile_campaign(campaign_id, plan, challenges, nodes, systems, context)`, `connector_id(system)`, `unit_id(...)`; tipos `CompiledCampaign`, `CompilerError`; tabla `CONNECTOR_IDS` | Compilador de campañas |
| Tablas | `argos.campaigns` (ampliada), `argos.campaign_units`, `argos.verdicts`, `argos.approval_requests`, `argos.approvals` (migración `0012`) | Campañas, unidades, veredictos y compuertas |
| Funciones | `create_campaign`, `pin_campaign`, `save_units`, `persist_verdict`, `request_approval`, `grant_approval`, `set_status`, `campaign_record`; `CampaignStateError`, `STATUSES`, `TRANSITIONS` | Almacén del motor (única escritura de veredictos) |
| Asientos | `campaign.create`, `campaign.pin`, `approval.request`, `approval.grant`, `verdict.emit` | Trazabilidad de la campaña |
| Funciones | `evaluate(unit, probe_result, opa_decision=None)`; tipo `Verdict` (`canonical()`, `hash`); constantes `RESULTS`, `OPERATORS` | Evaluador determinista (única fuente de veredictos) |
| Funciones | `sample_size`, `wilson_upper`, `required_sample_size`, `plan_sampling`; tipo `SamplingPlan`; constantes `Z`, `POPULATION_THRESHOLD` | Muestreo estadístico declarado |
| Tablas | `argos.synthetic_subjects`, `argos.synthetic_injections` (migración `0011`) | Inventario auditado de sujetos sintéticos |
| Funciones | `generate_subjects(seed, count)`, `is_synthetic(value)`, `client_package(subject, injections)`, `register_subjects`, `authorize_injection`, `confirm_injection`, `confirm_exercise`, `confirm_revert`, `pending_reversions`; tipos `SyntheticSubject`, `SyntheticError` | Sujeto sintético |
| Asientos | `synthetic.generate`, `synthetic.authorize`, `synthetic.injected`, `synthetic.exercised`, `synthetic.revert` | Trazabilidad del sujeto sintético |
| Herramienta de desarrollo | `tools/demo_client_actions.py inject\|erase\|revert` | Hace de cliente en la demostración (fuera del producto) |

## 5. Configuración

`ARGOS_TEMPORAL_ADDRESS`, `ARGOS_DATABASE_URL`, `ARGOS_NATS_URL`, `ARGOS_VAULT_ADDR`, `ARGOS_VAULT_TOKEN`, `ARGOS_OPA_URL` (por defecto `http://127.0.0.1:8181`), `ARGOS_OIDC_ISSUER` y `ARGOS_OIDC_AUDIENCE`, desde `argos-common`.

`ARGOS_API_BIND` es propia del proceso de la API: la dirección a la que se ata uvicorn. Por defecto `127.0.0.1`; el contenedor la pone a `0.0.0.0` porque el puerto publicado ya limita el acceso al bucle local del anfitrión.

Dependencias: `argos-common`, `argos-ontology`, el SDK de Temporal, `jsonschema` 4.23 y PyYAML.

## 6. Seguridad y tratamiento de datos

- Cada actividad que produce un resultado relevante lo anota en el diario de auditoría encadenado.
- El workflow de humo no accede a sistemas del cliente.
- **La IA no puede emitir un veredicto, y no es una promesa escrita sino tres cierres** (F06-01): ningún módulo del gateway de IA alcanza `evaluator`, `store` ni `findings` por ninguna ruta de importación (test arquitectónico que sigue el grafo real); el rol `argos_ai` de PostgreSQL puede leer veredictos y hallazgos —redactar el informe es su oficio— pero no tiene privilegio para escribirlos; y el contenedor no comparte red con la API de campañas.
- La imagen no lleva secretos: ninguna instrucción `ENV` ni `ARG` define credenciales, y las que necesita el entorno de desarrollo las pone el compose. Corre como el usuario sin privilegios `10001`.

## 7. Operación

- Temporal en desarrollo en `127.0.0.1:7233`.
- Una sola imagen, `argos-challenge-engine`, con un punto de entrada: `python -m argos_challenges.worker` (cola `argos-campaigns`). El worker también escucha `argos.campaign.circuit_open` y lo traduce en la señal `circuit_open` de cada campaña en marcha.
- `make dev` levanta el servicio `challenge-worker` de `deploy/dev/compose.yaml`; las rutas las sirve el servicio `api`.
- `make build` construye la imagen etiquetada con `org.argos.component=ARG-043` y `org.argos.version`; el CI genera su SBOM junto al de `argos-example`.
- Fuera del contenedor, ambos procesos se arrancan igual con `uv run python -m …`.

## 8. Verificación

`tests/integration/test_temporal.py`: ejecución del workflow de humo, reintentos de actividades y asiento en el diario contra Temporal real.

**Verdad terreno de campaña (Fase 05, F05-01):**
- `tests/fixtures/campaign_ground_truth.yaml` fija a mano, antes de que exista el motor, el resultado esperado por reto y sistema sobre la instantánea de demostración: 20 retos de RGPD y AI Act, 2 sin variante y el agregado por sistema;
- los incumplimientos plantados son:
  - una cuenta de facturación con lectura sobre la réplica con datos de salud y un perfil no autorizado;
  - un tratamiento sin base jurídica en el registro sintético (`deploy/dev/ropa/treatments.csv`);
  - el sujeto sintético que reaparece en la réplica;
  - el sistema de IA de alto riesgo sin documentación técnica;
- `tests/integration/test_planted_findings.py` comprueba en las fuentes simuladas cada hecho del que depende: TLS, cifrado en reposo, registro de accesos, cuenta plantada, registros fuera de plazo y registro de tratamientos;
- está pendiente de validación jurídica, como las poblaciones.

**Vectores de muestreo (F05-02):** `tests/fixtures/sampling_vectors.yaml` fija, calculados a mano y con el cálculo anotado, los valores que deben dar `sample_size`, `wilson_upper` y `required_sample_size`:
- `sample_size(10 000)` es 370; el documento de fase decía 371.
- Con 0 fallos, el tamaño que garantiza una cota inferior al 1 % es 381.

`services/challenge-engine/tests/test_sampling_vectors.py` los contrasta; queda como fallo esperado estricto hasta que exista el módulo de muestreo.

**Suite de determinismo del veredicto (F05-03):**
- `tests/fixtures/determinism/` contiene 11 casos con las entradas, los bytes canónicos esperados del veredicto (escritos a mano) y su SHA-256, uno por vía y por cada uno de los cuatro resultados, incluido el muestreo que no permite absolver.
- `test_verdict_determinism.py` comprueba que los bytes son canónicos y no contienen flotantes, y que el evaluador los reproduce dos veces seguidas.
- Se ejecuta en CI (Linux) y en local (Windows).

**Frontera de veredictos (F05-04):** `tests/architecture/` analiza el código con `ast`, sin importarlo, y falla si:
- algún módulo fuera de `argos_challenges.evaluator` construye un `Verdict`, también con alias, a través del módulo o escondido tras un `import *`;
- algún módulo fuera de `argos_challenges.store` escribe en `argos.verdicts` (leerla sí está permitido);
- el evaluador importa un paquete de modelos de lenguaje.

Seis infracciones plantadas comprueban que el analizador las detecta, y el repositorio pasa sin ninguna.

**DSL (F05-05):** `test_challenge_translation.py` (ida y vuelta, clave y valor desconocidos, clave duplicada y un campo dado a la vez en los dos idiomas) y `test_challenge_dsl.py` (esquema válido, diez documentos rechazados, plantilla de texto rechazada, parámetros tipados aceptados, las seis reglas del producto y los retos que se entregan). `tests/unit/test_challenge_lint_tool.py` comprueba los códigos de salida de la herramienta.

**Subsanación (F05-16):** `tests/integration/test_remediation.py` contra Temporal real: lo que el cliente arregló se cierra y lo que no se reabre, la reapertura no suma ocurrencia, la reejecución usa la unidad guardada con su versión en una campaña propia, y sin hallazgos pendientes no hay nada que verificar.

**API (F05-15):** `test_campaign_api_pure.py` con un validador falso (sin token 401, sin rol 403, solo el gestor lanza, solo el revisor aprueba, doble control con dos personas distintas y arranque sin motor que responde 503) y `tests/integration/test_campaign_api.py` con tokens reales del realm: el DPO aprueba y el diario guarda quién, los roles cruzados se rechazan, veredictos y hallazgos se leen y una transición ilegal da 409.

**Workflow y sello (F05-14):** `test_seal_pure.py` (qué cubre el sello, orden indiferente, cualquier cambio lo rompe) y `tests/integration/test_campaign_workflow.py` contra Temporal real: la campaña espera su compuerta, ejecuta, sella y `verify_seal` da verdadero; tras alterar un veredicto en la base, da falso.

**Hallazgos (F05-13):** `test_findings_pure.py` (huella, máquina de estados cerrada, cierre solo por verificación y escalado por recurrencia) y `tests/integration/test_findings.py` (una campaña no cuenta dos veces, tres campañas suben la severidad una sola vez, cierre solo por verificación, riesgo aceptado documentado que caduca a `reopened`, reapertura que no suma ocurrencia y huella única en la base).

**Actividades (F05-12):** `test_activities_pure.py` (solo salen las claves declaradas, ni valores ni cadenas de conexión, captura desconocida que no deja pasar nada, parámetros sin plantillas y lista cerrada de consultas internas de solo lectura) y `tests/integration/test_challenge_activities.py` (sonda real sobre la fuente simulada, evaluación idempotente, consulta interna desconocida rechazada sin reintento, sistema no registrado y asiento previo `query.emit`).

**Compilador y resolución sobre instantánea (F05-11):** `test_compiler_pure.py` (identificadores de conector, unidad completa y explicable, parámetros tipados resueltos, orden estable, sin variante a `unverifiable`, referencias que faltan y filas del plan sin reto o sin nodo como error, y sonda de muestra que exige aprobación) y `tests/integration/test_snapshot_resolver.py` (equivalencia con el grafo vivo en las nueve clases, `status` conservado y la instantánea que no se mueve cuando el grafo sí).

**Almacén (F05-10):** `tests/integration/test_challenge_store.py`: campaña creada, fijada y legible; se fija una sola vez; el mismo veredicto se escribe una vez aunque se repita; veredictos inmutables; resultado desconocido rechazado por la base; compuerta sin petición previa rechazada y doble control con personas distintas; petición repetida que conserva la primera; y estados que solo avanzan.

**Evaluador (F05-09):** los 11 casos de la suite de determinismo, ya sin marca de fallo esperado, y `test_evaluator_pure.py`: los seis operadores deciden en los dos sentidos, rutas con índices, evidencia que no responde, comparaciones entre tipos distintos que nunca lanzan, decisiones de OPA mal formadas, sonda fallida que no abre hallazgo, muestra que no absuelve y veredicto estable y con hash.

**Muestreo (F05-08):** los 11 vectores calculados a mano de F05-02, ya sin marca de fallo esperado, más `test_sampling_pure.py`: censo por debajo del umbral, muestra por encima, la unidad recibida no cambia, la cota baja al crecer la muestra y sube con los fallos, la muestra necesaria es la menor que lo demuestra, y siete argumentos imposibles rechazados.

**Sujeto sintético (F05-07):** `test_synthetic_pure.py` (determinismo por semilla, marcas válidas y reconocibles, rango que no toca la verdad terreno del inventario, paquete del cliente) y `tests/integration/test_synthetic_subjects.py` (la base guarda hashes y nunca valores en claro, solo una persona autoriza y solo con reversión, confirmaciones de escritura única y en el diario, derecho desconocido rechazado, sujetos inmutables, y el script del cliente que deja el sujeto plantado en la réplica).

**Biblioteca (F05-06):** `test_challenge_library.py` comprueba las familias, la carga por id, que el catálogo generado coincide con el que se entrega y es estable, que los ids reservados quedan como borrador, que el archivo congela una versión y rechaza cambiarla, y que el archivo no es fuente de retos.

### Biblioteca que se entrega (F05-18)

17 retos escritos sobre dos normas, con sus variantes por conector:

| Familia | Retos |
|---|---|
| `sec` | `sec-encryption-at-rest`, `sec-encryption-in-transit`, `sec-access-logging` |
| `acc` | `acc-special-category-profiles` (criterio en `argos.access`) |
| `ret` | `ret-table-retention` (criterio en `argos.retention`), `ret-file-retention` (solo conector de ficheros) |
| `dsr` | `dsr-erasure-effective`, `dsr-access-request-term` (ambos sobre el sujeto sintético) |
| `coh` | `coh-ropa-declared-systems`, `coh-treatment-legal-basis`, `coh-treatment-retention-declared`, `coh-unclassified-columns`, `coh-no-prohibited-ai-in-use`, `coh-ai-risk-class-declared`, `coh-ai-pending-review` |
| `doc` | `doc-ai-technical-documentation`, `doc-ai-human-oversight` |

- **Los criterios delegados leen la sonda:** `argos.retention` y `argos.access` toman el recuento y las identidades de `input.result`, lo que el reto declara en `input_map` son los parámetros del cliente. Sin una sola identidad, `argos.access` no absuelve: no hay evidencia con la que hacerlo.
- **El sujeto sintético llega al compilador regenerado desde su semilla:** `campaign_subject` lee la semilla y el índice que guarda la base (nunca los valores en claro) y reproduce los marcadores en memoria para que un reto pueda buscarlos en el sistema del cliente.
- **La sonda `shacl` se acota al sistema de la unidad** (el propio sistema, los tratamientos que declara y sus sistemas de IA) **y se filtra por forma y por severidad**, y así dos retos distintos (base jurídica y plazo de conservación) se apoyan en la misma forma sin confundirse.
- **Una referencia que el contexto no resuelve no rompe la campaña:** la unidad sale como `unverifiable` con su motivo (`MissingReferenceError`), igual que un reto sin variante para el conector.
- **Una consulta interna sin respuesta no es un cero:** devuelve un resultado sin el campo, y el evaluador lo convierte en `inconclusive`. De ahí que `dsr-access-request-term` quede sin resolver en un sistema contra el que no se ejerció el derecho.

## 9. Limitaciones conocidas y pendientes

- **Cuatro ids siguen reservados** (`draft` en el catálogo) porque la demostración no tiene de dónde sacar la evidencia: `brc-breach-register` (no hay registro de brechas), `coh-ai-training-data-governance` (no hay declaración de datos de entrenamiento) y `sec-ai-event-logging` y `sec-ai-log-retention` (el servicio del modelo queda fuera de las fuentes simuladas). Escribir un reto que solo puede responder `inconclusive` sería relleno.
- **La columna de referencia de la retención va escrita en cada variante** (`created_at`, `issued_at`): el nombre de una columna no puede viajar como parámetro de una sentencia.
- **`acc-special-category-profiles` deja fuera las cuentas de superusuario**: son cuentas técnicas de administración y se revisan aparte.
- El contenedor de la API valida los tokens emitidos por Keycloak en su dirección interna (`http://keycloak:8080/realms/argos`); desde el anfitrión, Keycloak responde en `127.0.0.1:8180` y los emisores no coinciden. Para ejercer la API autenticada desde el anfitrión se usa el proceso local, como hacen los tests de F05-15.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Worker de Temporal con workflow de humo, reintentos y asientos en el diario | Fase 01 (ARG-007) |
| 0.1.0-alpha | 2026-09-17 | Incumplimientos plantados y verdad terreno de campaña para la prueba de la Fase 05 | Fase 05 (F05-01) |
| 0.1.0-alpha | 2026-09-17 | Vectores de muestreo y cota de Wilson calculados a mano | Fase 05 (F05-02) |
| 0.1.0-alpha | 2026-09-17 | Suite de determinismo del veredicto con bytes canónicos esperados | Fase 05 (F05-03) |
| 0.1.0-alpha | 2026-09-17 | Test arquitectónico de la frontera de veredictos | Fase 05 (F05-04) |
| 0.1.0-alpha | 2026-09-17 | DSL de retos con esquema, capa de traducción en castellano, lint y retos patrón | Fase 05 (ARG-041) |
| 0.1.0-alpha | 2026-09-17 | Biblioteca por familias, catálogo generado y archivo por versión | Fase 05 (ARG-050) |
| 0.1.0-alpha | 2026-09-17 | Sujeto sintético: generación marcada, inventario auditado, confirmaciones del cliente y script de demostración | Fase 05 (ADR-0008) |
| 0.1.0-alpha | 2026-09-17 | Muestreo con corrección finita, cota superior de Wilson y muestra necesaria | Fase 05 (ARG-045) |
| 0.1.0-alpha | 2026-09-17 | Evaluador determinista puro con veredicto de cuatro valores y hash canónico | Fase 05 (ARG-046) |
| 0.1.0-alpha | 2026-09-17 | Tablas de campañas, unidades, veredictos y aprobaciones, y almacén idempotente | Fase 05 (ARG-043) |
| 0.1.0-alpha | 2026-09-17 | API de campañas con compuertas de doble control y confirmaciones del cliente | Fase 05 (ARG-047) |
| 0.1.0-alpha | 2026-09-17 | Reejecución de subsanación con la unidad original y transición verificada | Fase 05 (ARG-049) |
| 0.1.0-alpha | 2026-09-17 | Resolución de selectores sobre la instantánea y compilador de campañas con parámetros tipados | Fase 05 (ARG-042) |
| 0.1.0-alpha | 2026-09-17 | Actividades de sonda con minimización, ventanas, sondas internas y evaluación persistida | Fase 05 (ARG-044) |
| 0.1.0-alpha | 2026-09-17 | Ciclo de vida de los hallazgos con deduplicación, escalado y riesgo aceptado con caducidad | Fase 05 (ARG-048) |
| 0.1.0-alpha | 2026-09-17 | Workflow de campaña con compuertas y pausa por cortacircuitos, y sello verificable | Fase 05 (ARG-043) |
| 0.1.0-alpha | 2026-09-17 | Contenedores del worker y de la API en el entorno de desarrollo, con SBOM en el CI | Fase 05 (F05-17) |
| 0.1.0-alpha | 2026-09-17 | Biblioteca de 17 retos de RGPD y AI Act, criterios delegados que leen la sonda y filtro por severidad en SHACL | Fase 05 (ARG-050) |
| 0.1.0-alpha | 2026-09-17 | Prueba de la fase: campaña completa, reejecución determinista, sello y subsanación | Fase 05 (`fase-05`) |
| 0.1.0-alpha | 2026-09-18 | El worker se conecta al bus y anuncia cada sello en `argos.campaign.sealed` (dependencia de `argos-events`) | F07-13 |
| 0.1.0-alpha | 2026-09-21 | Lectores para la API v1 en `store`: `list_campaigns`, `campaign_gates`, `campaign_plan` (unidades literales y lo no verificable, antes de sondear) y `approvals_needed`; la API de la Fase 05 lee las compuertas con la misma función | F08-05 |
| 0.1.0-alpha | 2026-09-21 | Hallazgos: una persona ya no lleva un hallazgo a `closed_compliant` ni a `reopened` (solo la reejecución, con actor `system:`); `person_transitions`, `list_findings` (peor primero, con filtros) y `finding_detail` (veredicto y asiento de la consulta); la subsanación admite un único hallazgo (`finding_id`) | F08-06 |
| 0.1.0-alpha | 2026-09-21 | La compuerta pendiente se anuncia en el bus (`argos.campaign.approval_requested`) una sola vez, cuando se abre; `request_approval` devuelve si la abrió | F08-09 |
| 0.1.0-alpha | 2026-09-21 | La señal `circuit_open` admite un motivo opcional y la consulta `progress` devuelve los sistemas en pausa con él; `campaign_gates` incluye `approved_by` | F08-12 |
| 0.1.0-alpha | 2026-09-22 | `finding_detail` trae `history` (los asientos `finding.open`, `finding.recur` y `finding.transition` del hallazgo, en orden) y lee la declaración muestral de donde la deja el evaluador (`verdict.detail.sampling`); antes salía siempre vacía | F08-13 |
| 0.1.0-alpha | 2026-09-22 | Retirada de `argos_challenges.api`: las rutas son las de la API única. Nuevos `store.list_verdicts` y `store.running_campaigns`, y el puente `bridge.on_circuit_open`, que convierte el cortacircuitos del conector en la pausa de la campaña | F08-17 |
| 0.1.0-alpha | 2026-09-22 | La pausa de un sistema caduca: el workflow espera `circuit_closed` como mucho `PAUSE_MAX` (300 s, el enfriamiento del conector). Nadie envía hoy esa señal —el conector solo anuncia la apertura—, y sin cota una campaña se quedaba esperando para siempre | F08-17 |
