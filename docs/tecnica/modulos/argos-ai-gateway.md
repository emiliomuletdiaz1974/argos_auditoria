---
id: MOD-argos-ai-gateway
kind: module
title: Gateway de IA local (argos-ai-gateway)
module: argos-ai-gateway
phases: ["06"]
version: 0.1.0-alpha
commit: 06fb0ef
date: 2026-09-17
status: draft
confidentiality: client
---

# Gateway de IA local (argos-ai-gateway)

## 1. Propósito

La capa de IA de ARGOS, entera dentro del perímetro del cliente: ni una llamada al exterior (P-03 del pliego). Es un **servicio auxiliar** con cuatro oficios —clasificar lo ambiguo, proponer retos desde texto normativo, redactar dictámenes y asistir en la consola— y dos prohibiciones que esta capa **implementa**, no declara: nunca decide conformidad y nunca ve datos del cliente en claro.

Implementa ARG-051 a ARG-060. En su estado actual contiene los guardarraíles (ARG-060); el resto llega en las tareas siguientes de la Fase 06, y este documento está en estado `draft` hasta entonces.

## 2. Alcance y límites

- **Hace:** depurar lo que entra a un prompt, vigilar lo que sale y ser **la única puerta a la inferencia**: colas con dos prioridades, cuota diaria por servicio, JSON forzado con un ciclo de reparación y registro con hash.
- **Hará:** asistente con herramientas (ARG-058) y el arnés de evaluación (ARG-059).
- **No hace, y no es una cuestión de configuración:** emitir un veredicto. No hay ruta de importación, ni de red, ni de permisos de base de datos que lleve de aquí al evaluador.
- **No hace:** escribir en un sistema del cliente, ni proponer que se escriba.

## 3. Arquitectura

- **`argos_ai.guardrails`** (ARG-060): `scrub_input` a la entrada y `check_output` a la salida. Puro, sin modelo y sin entrada/salida, para poder probarlo entero.
- **`argos_ai.gateway.Gateway`** (ARG-052): la puerta. El diario y el registro de uso se inyectan, así que el gateway se ejerce entero sin base de datos; `argos_ai.quotas.postgres_gateway` lo monta como corre en el appliance.
- **`argos_ai.rag`** (ARG-053, ARG-054): troceado por estructura jurídica, embeddings, índice sobre pgvector y el pipeline de respuesta con cita obligatoria.
- **`argos_ai.classify`** (ARG-055): el clasificador semántico que rellena la interfaz ARG-025 de la Fase 03, con la confianza calibrada por las decisiones del DPD.
- **`argos_ai.generate`** (ARG-056): el generador asistido de retos y la herramienta `tools/new_challenge.py` del equipo normativo.
- **`argos_ai.reports`** (ARG-057): el redactor del expediente, con el verificador de cifras y la marca de texto asistido.
- **`argos_ai.assistant`** (ARG-058): el asistente de consola, un agente con cuatro herramientas cerradas de solo lectura.
- **`argos_ai.evaluation`** (ARG-059): el arnés que mide cada oficio contra sus conjuntos dorados y la puerta de calidad.
- **`argos_ai.backends`**: un contrato (`Backend`, `Completion`) y tres implementaciones. `OpenAiCompatibleBackend` sirve para vLLM y para llama.cpp, porque los dos hablan la misma API; `FakeBackend` responde desde un fichero indexado por el hash del prompt.
- Dependencias: `argos-common` (errores y configuración) y `argos-connector-sdk`, del que reutiliza los **validadores de identificadores españoles de ARG-024**.

### La barrera (F06-01)

Tres cierres, no una promesa escrita:

1. **Importaciones:** `tests/architecture/ai_boundary.py` sigue el grafo de importaciones real del espacio de trabajo y rechaza que cualquier módulo de este paquete alcance `argos_challenges.evaluator`, `.store` o `.findings`, aunque el cable esté atado tres módulos más allá.
2. **Permisos:** el rol `argos_ai` de PostgreSQL (migración `0015`) lee el esquema y escribe solo `argos.ai_usage`. Leer veredictos y hallazgos sí: redactar el informe desde ellos es el oficio de ARG-057.
3. **Red:** el contenedor no comparte red con la API de campañas. Se comprueba **desde dentro del contenedor** (`tests/integration/test_ai_containers.py`): para el gateway, `challenge-api` no existe. La base la alcanza por su propia red (`ai-data`) y con la sesión en el rol `argos_ai`, así que desde dentro escribir un veredicto también se deniega.

### El gateway (ARG-052)

- **Dos prioridades con semáforo:** `interactive` (asistente y consola) reserva plazas para que el trabajo por lotes —clasificación nocturna, dictámenes— no la deje sin turno.
- **Cuota diaria por servicio, en tabla** (`argos.ai_quotas`, migración `0016`), consultada **antes** de llamar al modelo: gastar primero y quejarse después dejaría la cuota de adorno. Un servicio sin fila no puede gastar: el valor por defecto es cero, no infinito. Lo gastado hoy sale de `argos.ai_usage`, así que un reinicio no regala presupuesto.
- **JSON forzado con un ciclo de reparación:** el esquema viaja al backend para que guíe la decodificación, pero la respuesta **se valida siempre aquí**; si no encaja, vuelve con su error como realimentación. Un ciclo, no un reintento infinito.
- **Registro:** una fila en `argos.ai_usage` y un asiento `ai.completion` en el diario encadenado, los dos con el **hash del prompt y nunca el prompt**.

### El backend determinista, que es producto

Sin él el CI dependería de una GPU y del humor de un modelo, y un conjunto dorado que cambia bajo los pies no mide nada. Responde desde un fichero indexado por el hash del prompt, y **una entrada que no conoce es un error**: un valor por defecto en silencio convertiría un caso que falta en una suite verde.

### El corpus indexable (ARG-053)

- **Se trocea por estructura jurídica, no por tamaño ciego.** Un fragmento es un apartado con la cabecera de su artículo como contexto, porque «a) la seudonimización» a solas no dice nada. Solo un apartado que de verdad no cabe se parte, y entonces **su cita lo dice** con un sufijo en vez de fingir que es el apartado entero. Un preámbulo no es un artículo y no recibe cita: inventarla sería peor que perderlo.
- **La referencia es el punto de la tabla:** `RGPD art. 32.1.a`. Un fragmento que un DPO no puede citar no le sirve de nada.
- **El origen** (`norm`, `guide`, `client`) permite citar con propiedad: lo que dice la norma no es lo que dice el procedimiento del cliente.
- **Idempotente por hash de fragmento:** reindexar no duplica una fila ni mueve un vector. Importa más de lo que parece — el corpus se reindexa en cada actualización de contenido, y un índice que se desplaza hace que la cita de ayer apunte hoy a otro sitio.
- **Dos búsquedas sobre la misma tabla:** vectorial con índice HNSW y léxica con `tsvector`, porque los números de artículo son justo lo que peor tratan los embeddings y justo lo que un DPO escribe.
- **El embebedor es configuración.** En los tests, `HashEmbedder` da un vector estable por texto: no entiende nada, pero es determinista, y la calidad semántica se mide contra el modelo real en los conjuntos dorados.

### El RAG normativo (ARG-054)

La exigencia está por encima de la habitual: **la cita exacta**. «El RGPD exige X» sin apartado es ruido para un DPO; «art. 32.1.a» con el fragmento al lado es una herramienta.

- **Recuperación híbrida y fusión RRF.** Vectorial y léxica devuelven puntuaciones que no viven en la misma escala, así que no se suman: RRF suma posiciones. Lo que las dos búsquedas encuentran gana a lo que encuentra solo una, aunque esa lo ponga primero. Lo que **no** hace es premiar el término medio: por convexidad, primero en una y tercero en la otra supera a segundo en las dos.
- **Contexto numerado y cita obligada.** Los fragmentos van numerados y el prompt obliga a citarlos por número.
- **Toda cita se comprueba contra lo que se recuperó.** Una cita inventada **invalida la respuesta**: es peor que no responder.
- **Rehúso honesto.** Sin soporte suficiente, la respuesta lo dice y enseña los fragmentos más cercanos por si el humano quiere juzgar. «No encuentro base normativa en el corpus» es una respuesta correcta del producto, no un fallo.
- Con el corpus vacío ni siquiera se llama al modelo.

### Clasificación semántica calibrada (ARG-055)

Un modelo dice 0,9 y acierta 0,7. Sin corregirlo, los umbrales de ARG-025 —aceptar desde 0,85, revisar desde 0,50— serían números arbitrarios.

- **Rellena la interfaz de la Fase 03 sin tocarla.** `SemanticClassifier.propose(columns)` es el `ClassificationModel` que el inventario llevaba esperando desde F03-07: la cola, los umbrales y el triaje siguen donde estaban. Solo viajan metadatos: nombre, tipo, tabla y nombres de las hermanas, nunca un valor.
- **Cada decisión del DPD es una etiqueta gratis.** El modelo declaró una confianza y la persona dijo acierto o fallo. Una **regresión isotónica por categoría** sobre esos pares traduce lo que el modelo declara a lo que de verdad ha conseguido. Isotónica porque lo único que se supone es que declarar más no puede significar acertar menos. Se implementa con *pool adjacent violators*, sin dependencias.
- **Por debajo de 50 decisiones no hay curva en la que confiar**, ni motivo para confiar en el modelo: la calibración es la identidad con techo en **0,8**. Ese techo está a propósito por debajo del umbral de aceptación: un modelo sin calibrar puede llenar la cola de revisión, pero no clasificar nada solo.
- **Se guarda la confianza declarada, no la calibrada** (`argos.ai_proposals`). La cola de ARG-025 guarda la calibrada, porque es la que usó el triaje, y ajustar la curva siguiente sobre ella la alimentaría con su propia salida.
- **El prompt es un fichero versionado** (`library/prompts/classify.yaml`) y su SHA-256 va con el clasificador: cambiar el prompt es cambiar el clasificador, y las curvas se reajustan después.
- **`refit(dsn)`** es el trabajo nocturno: reajusta las curvas con las decisiones nuevas, las guarda en `argos.ai_calibration` y lo anota en el diario. **`drift(dsn)`** da la precisión de los últimos 30 días por categoría, la señal que publicará ARG-059.

### Generación asistida de retos (ARG-056)

El SLA de 30 días de norma a reto y los 300 retos de GA no salen de escribir YAML a mano. **El flujo humano manda:** el jurista pega la obligación, el modelo propone y un ingeniero revisa.

- **El jurista solo ve propuestas que ya compilan.** El prompt lleva el esquema del DSL, el catálogo de sondas y dos retos completos de la biblioteca como ejemplo, leídos del propio repositorio para que no se desfasen. La propuesta pasa por **el mismo `lint_challenge` de la CI**, en memoria; si falla, un ciclo de reparación con sus errores, y si sigue fallando se devuelve como no válida.
- **Una sonda que escribe no se repara: se rechaza.** Repararla le enseñaría al modelo a colar una escritura por el lint. Toda sentencia declarada tiene que ser `SELECT`, `SHOW` o `WITH` y no contener verbos de escritura; y los guardarraíles de ARG-060 la vuelven a rechazar en el gateway si llegara hasta allí, antes de anotarla como uso válido.
- **La propuesta entra en Git como rama de revisión, nunca directamente en la biblioteca.** `tools/new_challenge.py` prepara la rama `feature/reto-<id>` en un *worktree* temporal: la copia de trabajo del jurista, su índice y su rama actual quedan exactamente como estaban. Una rama que ya existe no se sobrescribe —la propuesta anterior no se entierra sin revisar—, una propuesta no válida no llega a Git y nada se publica: subir la rama es decisión de una persona.

### Dictámenes con cifras verificadas (ARG-057)

El expediente necesita dos textos que hoy cuestan horas de consultor: el resumen ejecutivo y la narrativa de cada hallazgo. El modelo los redacta desde los datos estructurados de la campaña, con tres reglas que no se doblan:

1. **Toda cifra del texto es una cifra de sus datos.** El verificador extrae cada número y lo busca entre los que se le dieron. No acepta sumas, ni cocientes, ni redondeos: el modelo no hace aritmética para el expediente, aunque acierte (120 de 166 es un 72,29 %, y un «72,3 %» se rechaza igual). Lo que sí tolera es el **formato**: «1.200» es 1200, «0,85» es 0,85 y «85 %» puede citar un cociente de 0,85. Los números dentro de identificadores (`OBL-RGPD-32-1`) y de **referencias legales** («artículo 32», «art. 32.1.a», «apartado 2») no son cantidades y no se comprueban.
2. **El texto nunca altera un veredicto.** El resumen solo puede citar veredictos de su propia campaña, y la narrativa de un hallazgo no puede afirmar la conformidad que su veredicto negó («es conforme», «cumple», «no procede»). Decir «no es conforme» sí puede: eso no es discutir el veredicto, es el veredicto.
3. **Toda pieza queda marcada** `generated`, con el hash de su prompt, en `argos.report_texts`: la marca que el expediente de la Fase 07 enseña al supervisor.

**Un borrador que rompe una regla no se guarda en absoluto**, ni siquiera con un aviso. Y lo que se guarda no se edita: la tabla es de escritura única, y un borrador nuevo es una fila nueva. Los casos trampa de los conjuntos dorados de F06-02, escritos antes que el verificador, se ejecutan tal cual como test.

### Asistente de consola con herramientas cerradas (ARG-058)

Responde preguntas de tres mundos —la normativa, el estado del cliente y las dos cosas a la vez— con un **agente de herramientas cerradas**: elige entre cuatro herramientas de solo lectura con parámetros tipados y va iterando hasta poder responder.

| Herramienta | Qué lee | Parámetros |
|---|---|---|
| `search_regulation` | El corpus normativo (ARG-054), con fragmentos citables | la pregunta, de 3 a 300 caracteres |
| `finding_status` | Recuentos de hallazgos por estado y severidad | `status` y `severity` cerrados, `system_id` UUID, `challenge_id` con patrón |
| `inventory_coverage` | La cobertura del catálogo (ARG-026) | `system_id` opcional |
| `query_graph` | El selector de la lista blanca de la API del inventario (ARG-029), el mismo que usa el motor de retos | solo los campos del selector |

- **Nunca un lenguaje de consulta.** Ninguna herramienta acepta SQL, Cypher ni un filtro escrito como texto: cada una construye su propia consulta parametrizada. Un test comprueba que ningún esquema tenga un campo así.
- **Tres cosas fijas que la pregunta no puede mover:** el **presupuesto** de cinco llamadas por pregunta —si no basta, la respuesta lo dice en vez de adivinar—; los **argumentos**, validados contra el esquema antes de ejecutar nada, de modo que una llamada inválida vuelve al modelo con su error y gasta presupuesto igual; y las **fuentes**: cada fuente que cita la respuesta tiene que ser una herramienta que de verdad devolvió datos, igual que una cita del RAG tiene que ser un fragmento recuperado.
- **Defensa en profundidad:** un paso del modelo que lleve una sentencia de escritura lo para el guardarraíl del gateway antes de que el agente llegue a buscar la herramienta.
- **La conversación vive solo en memoria**, para la pregunta en curso; lo que queda registrado es el hash de cada prompt, nunca su contenido.

### Arnés de evaluación con conjuntos dorados (ARG-059)

«La IA funciona bien» es, en ARGOS, una afirmación con evidencia. Cada oficio responde a cada caso de su conjunto dorado (F06-02); la nota de un conjunto es la proporción ponderada de aciertos, y la puerta la compara con el umbral escrito —con su motivo— en `goldens/thresholds.yaml`. **Las trampas pesan el doble**, porque miden el rehúso, que es la virtud más difícil.

**Dos modos, con dos preguntas distintas:**

- **Oráculo** (`make ai-eval`, dentro de `make check`): el «modelo» responde a cada caso con su salida esperada. No mide el modelo; mide **todo lo demás**: que la recuperación alcance el fragmento que la respuesta cita, que las comprobaciones acepten lo correcto y rechacen las trampas, y que las notas y la puerta funcionen. Si el oráculo no llega a un umbral, el que pierde puntos es el pipeline. Corre sobre una base desechable.
- **Real** (`make ai-eval-release`, `tools/ai_eval/run_goldens.py`): el modelo servido. Su nota es la calidad del modelo y es la puerta de una release. Necesita los pesos (F06-05).

Un conjunto que desaparece, o un umbral sin su conjunto, es un error: el arnés no da por bueno lo que no midió.

**Lo que el arnés destapó la primera vez que corrió**, y por qué el embebedor de pruebas cambió: con el oráculo respondiendo perfecto, RAG sacó **0,68**. La búsqueda léxica ponía primero el artículo correcto, pero el embebedor de pruebas era ruido puro, y en la fusión RRF lo que coincidía por casualidad en las dos listas desplazaba al acierto léxico fuera del contexto. El pipeline estaba bien; el CI medía ruido. El embebedor determinista pasó a ser una bolsa de palabras con *feature hashing* —sin pesos, pero con señal— y RAG subió a **1,0**. Un test comprueba ahora que el embebedor ordena bien cinco preguntas contra seis fragmentos, algo que un embebedor de ruido no consigue ni una vez en 5000 intentos. La misma lección vale para producción: **con un embebedor flojo, la fusión puede empeorar un buen resultado léxico**; la puerta de release con el modelo real es la que lo vigila.

La búsqueda léxica pasó además a «cualquiera de las palabras» ordenado por relevancia, en lugar de «todas»: un DPO pregunta con frases, y «¿en cuántas horas hay que notificar una violación de datos?» tiene palabras que el artículo no usa.

### Guardarraíles (ARG-060)

- **`scrub_input(text) -> (clean, substitutions)`.** Sustituye por marcadores estables (`[DNI-1]`, `[IBAN-1]`) lo que **valida** como identificador español, reutilizando `argos_connector.validators`. La diferencia con una expresión regular ciega es el producto: un código de producto con la forma de un DNI pero sin su letra de control se queda intacto. El mismo valor recibe el mismo marcador dentro de un texto, para no destrozar el sentido de la frase.
- **`check_output(answer) -> bool`.** Recorre todas las cadenas del JSON, por hondas que estén, y rechaza dos cosas con motivo tipificado:
  - `veredicto_no_citado`: una afirmación de conformidad sobre un activo sin el `verdict_id` del que sale;
  - `escritura_sobre_objetivo`: un verbo de escritura sobre un sistema.
- **Las tablas de patrones son contenido**, en `library/prompts/guardrails.yaml`, y el equipo las amplía sin una release. **La decisión de rechazar no es contenido:** no tiene interruptor.

## 4. Interfaces

| Función | Firma | Consumidores |
|---|---|---|
| `scrub_input` | `(text: str) -> tuple[str, int]` | ARG-052, toda inferencia |
| `check_output` | `(answer: Mapping[str, Any]) -> bool` | ARG-052, toda inferencia |
| `load_patterns` | `(path: Path = PATTERNS_FILE) -> dict[str, Any]` | ARG-052, telemetría |
| `OutputRejectedError` | excepción con el motivo | cada oficio la maneja: reintento con aviso o rehúso |
| `Gateway.chat_json` | `(service, system, user, schema, priority="batch") -> Answer` | ARG-054…058 |
| `postgres_gateway` | `(dsn, backend, model="argos-llm") -> Gateway` | el proceso del appliance |
| `daily_quotas`, `spent_today` | `(dsn) -> dict[str, int]` | operación, panel de calidad |
| `chunk_legal_text` | `(text, norm) -> list[Chunk]` | ARG-053, ingesta del observatorio |
| `index_document`, `index_chunks` | `(dsn, source, origin, …, embedder) -> int` | ARG-054, documentación del cliente |
| `search`, `search_lexical` | `(dsn, query, …) -> list[Hit]` | ARG-054, ARG-058 |
| `answer` | `(dsn, question, gateway, embedder, origins=None) -> Answer` | ARG-056 (contexto), ARG-058 (herramienta normativa) |
| `reciprocal_rank_fusion` | `(rankings, k=60) -> list[str]` | ARG-054 |
| `SemanticClassifier` | `(gateway, calibrator, record=None).propose(columns)` | ARG-025 (inventario) |
| `Calibrator` | `fit(decisions)`, `calibrate(category, declared)`, `curves()` | ARG-055, ARG-059 |
| `refit`, `stored_calibrator`, `drift` | `(dsn, now=None)` | trabajo nocturno, panel de calidad |
| `propose_challenge` | `(obligation, text, gateway, context, regulation="") -> ChallengeProposal` | equipo normativo |
| `GET /health`, `POST /v1/chat_json` | servicio interno en `8005` | servicios de la plataforma |
| `tools/new_challenge.py` | `OBL-… "texto" [--repo]` → rama `feature/reto-<id>` | equipo normativo |
| `draft_summary`, `draft_finding_narrative` | `(dsn, id, gateway) -> str` (id del texto guardado) | Fase 07 (expediente) |
| `unsupported_figures`, `extract_figures` | `(text, data) -> list[str]` | ARG-057, ARG-059 |
| `ask` | `(question, gateway, tools) -> Answer(answer, sources, complete, calls)` | Fase 08 (chat de la consola) |
| `default_toolbox` | `(dsn, embedder) -> dict[str, Tool]` | ARG-058 |
| `evaluate_all` | `(dsn, embedder, backends=oracle_backends) -> list[SuiteReport]` | CI, release, panel de calidad |
| `score`, `gate`, `SuiteReport`, `TRAP_WEIGHT = 2` | nota ponderada y código de salida | CI |

## 5. Configuración

`ARGOS_LLM_LOCAL_ENDPOINT` (desde la Fase 01) y `ARGOS_LLM_MODEL` (ADR-0009): dirección del servidor compatible OpenAI y nombre del modelo servido. Ningún módulo nombra un modelo. Los guardarraíles no necesitan configuración: sus tablas son contenido, y la cuota vive en `argos.ai_quotas`.

## 6. Seguridad y tratamiento de datos

- Ningún dato personal validado llega al modelo: se sustituye antes por un marcador.
- Ningún prompt se escribe en un log ni en una tabla; lo que se registra es su hash (ARG-052, `argos.ai_usage`).
- El rol `argos_ai` puede **añadir** asientos al diario encadenado (migración `0020`, permiso de ejecución sobre `journal_append`, que es `SECURITY DEFINER`) y nada más sobre él. Hasta F06-13 no lo tenía: los tests del gateway conectaban como propietario y no lo veían. Ejecutar el gateway como lo hace el contenedor lo destapó.
- El paquete no puede escribir veredictos ni hallazgos, por código y por permisos.

## 7. Operación

- **El servicio:** `python -m argos_ai.api.main`, con dos puntos internos —`GET /health` y `POST /v1/chat_json`, el contrato de ARG-052—. Una cuota agotada es un 429, una salida que los guardarraíles rechazan es un 422 y una respuesta que no encaja tras la reparación es un 502. Es **interno a propósito**: su única protección en desarrollo es la red, como la NetworkPolicy del appliance.
- **El contenedor:** `services/ai-gateway/Dockerfile`, usuario sin privilegios, sin secretos y **sin pesos** (el modelo lo sirve su propio contenedor). `make dev` levanta `ai-gateway` en `127.0.0.1:8005` con healthcheck; `make build` construye `argos-ai-gateway:<versión>` con `org.argos.component=ARG-052` y el CI genera su SBOM.
- **Las redes:** `ai` (gateway y modelo) y `ai-data` (gateway y PostgreSQL). PostgreSQL está en las dos redes, la de siempre y `ai-data`; la API de campañas, solo en la de siempre.
- **El modelo:** el servicio `llm` (llama.cpp sobre CPU, API compatible OpenAI, ADR-0009) va en su propio perfil, `llm`, porque necesita los pesos de F06-05. Sin ellos, `make dev` funciona igual y `/v1/chat_json` responde 502.
- **La sesión de base de datos** corre como `argos_ai` (`options=-c role=argos_ai` en la cadena de conexión).

## 8. Verificación

`services/ai-gateway/tests/test_ai_api_pure.py`: salud, respuesta con su hash y sin su prompt, 429 por cuota, 422 por guardarraíl, 502 por esquema y prioridad desconocida rechazada.

`tests/integration/test_ai_containers.py`: salud del contenedor, la API de campañas inexistente desde dentro, la base alcanzada como `argos_ai`, la escritura de un veredicto denegada desde dentro y una imagen sin root, sin secretos y sin pesos. `tests/integration/test_ai_gateway.py` comprueba además que el gateway funciona entero bajo el rol restringido.

`services/ai-gateway/tests/test_eval_metrics_pure.py`: la nota calculada a mano, el doble peso de las trampas, un conjunto que pasa lo fácil y falla las trampas que no aprueba, un conjunto vacío que es error y no un 100 %, y un umbral sin su conjunto que cierra la puerta.

`services/ai-gateway/tests/test_embeddings_pure.py`: el embebedor de pruebas ordena bien cinco preguntas contra seis fragmentos, trata igual acentos y mayúsculas y nunca devuelve un vector nulo.

`tests/integration/test_ai_goldens.py` (`make ai-eval`): los cuatro conjuntos alcanzan su umbral con el oráculo y las trampas de redacción se rechazan.

`services/ai-gateway/tests/test_assistant_pure.py`: pregunta normativa con una herramienta, mixta con dos, argumento fuera de tipo que no llega a la herramienta, herramienta desconocida, paso con escritura parado por el guardarraíl, sexta llamada cortada, fuente no consultada y llamada fallida que no puede citarse, ninguna herramienta con lenguaje de consulta, presupuesto que la pregunta no puede subir y conversación que no se registra.

`tests/integration/test_assistant.py`: las cuatro herramientas contra la base real —incluido un campo fuera de la lista blanca del selector— y una pregunta de principio a fin.

`services/ai-gateway/tests/test_figures_pure.py`: los casos trampa dorados de F06-02, separador de miles, coma decimal, porcentaje que cita un cociente, aritmética del modelo rechazada, números de identificadores y referencias legales excluidos y todas las cifras que fallan, no solo la primera.

`services/ai-gateway/tests/test_writer_pure.py` y `tests/integration/test_report_writer.py`: resumen que se guarda marcado, cifra inventada que no guarda nada, veredicto de otra campaña rechazado, narrativa que discute su veredicto rechazada, «no es conforme» permitido y texto guardado que no se puede editar.

`services/ai-gateway/tests/test_challenge_gen_pure.py`: propuesta que compila, reparación en un ciclo con los errores del lint, propuesta que sigue fallando, YAML roto reparado, sonda de escritura rechazada sin reparación y prompt con esquema, sondas y dos ejemplos.

`tests/unit/test_new_challenge_tool.py`, sobre un repositorio git temporal: la propuesta en su propia rama, la copia de trabajo intacta, commit sin firmas, rama existente no sobrescrita y propuesta no válida que no llega a Git.

`tests/integration/test_challenge_generation.py`: la generación consume la cuota del servicio `challenge`, y una propuesta que escribe se para antes de anotarse como uso.

`services/ai-gateway/tests/test_calibration_pure.py`: la curva PAVA contra una calculada a mano, monotonía, empates en la confianza declarada tratados como un solo punto, modelo sobreconfiado bajado a su tasa real, techo por debajo del mínimo de datos, curva por categoría y guardado y lectura idénticos.

`services/ai-gateway/tests/test_classify_service_pure.py`: las propuestas que espera el inventario, la confianza calibrada que ve el triaje, un modelo sin calibrar que solo puede encolar, solo metadatos al modelo, el prompt versionado y la confianza declarada registrada en lugar de la calibrada.

`tests/integration/test_classify_service.py`: la curva aprendida de la confianza declarada y no de la encolada, guardada y leída, las decisiones pendientes que no cuentan como etiqueta, la deriva de 30 días y el registro del clasificador.

`services/ai-gateway/tests/test_rag_pure.py`: la fórmula de RRF contra números calculados a mano, la preferencia por el acuerdo, la cita inventada que invalida, la respuesta que se dice suficiente sin citar y el rehúso.

`tests/integration/test_rag_pipeline.py`: respuesta con cita real, cita inventada rechazada, pregunta fuera de corpus rehusada con sus fragmentos cercanos, corpus vacío sin llamar al modelo y número de artículo al alcance gracias a la mitad léxica.

`services/ai-gateway/tests/test_chunking_pure.py`: un apartado por fragmento con su cabecera, numeración no consecutiva respetada, apartado largo partido con sufijo, continuación de una letra que se queda en la letra, hashes estables y sin colisiones, y preámbulo descartado.

`tests/integration/test_rag_index.py`: indexación idempotente, fragmentos citables, dimensión del vector, búsqueda que encuentra lo que se le dio, filtro por origen y búsqueda léxica por número de artículo.

`services/ai-gateway/tests/test_gateway_pure.py`: esquema forzado y reparado en un ciclo, error si tras la reparación sigue sin encajar, cuota mirada antes de llamar, servicio sin cuota que no gasta, registro con hash y sin prompt, entrada depurada antes de llegar al modelo, salida que decide conformidad rechazada, cola interactiva que el trabajo por lotes no mata de hambre y backend determinista que rechaza lo que no conoce.

`tests/integration/test_ai_gateway.py`: cuotas leídas de la tabla, uso y asiento escritos, ni el prompt ni el dato personal en ninguna parte, y lo gastado hoy que sobrevive a un reinicio.

`services/ai-gateway/tests/test_guardrails_pure.py`: identificadores reales sustituidos y falsos intactos, marcador estable, conformidad sin veredicto rechazada y con veredicto permitida, verbos de escritura rechazados, texto anidado alcanzado y recomendación legítima no confundida con una orden.

`tests/architecture/test_ai_boundary.py` y `tests/integration/test_ai_boundary.py`: la barrera.

## 9. Limitaciones conocidas y pendientes

- Faltan el contenedor del gateway (F06-13) y el modelo real (F06-05); los diez componentes de código están.
- **El índice vectorial no guarda qué embebedor calculó cada vector** (pendiente anotado): mezclar embebedores en una misma base dejaría vectores de otro espacio sin error. Por eso el oráculo corre en una base desechable.
- El formato de paso del asistente es JSON sobre `chat_json`, no el *tool-calling* nativo del servidor: así funciona igual con llama.cpp, vLLM y el backend determinista. Con vLLM en el appliance puede pasarse al nativo sin cambiar las herramientas.
- La detección de una narrativa que discute su veredicto es una lista cerrada de expresiones; un modelo podría dar un rodeo que no recoja. Los conjuntos dorados del arnés (ARG-059) son los que miden si hace falta ampliarla.
- El reajuste nocturno de la calibración es una función (`refit`) pero aún no tiene planificador: se engancha a Temporal con la operación.
- La telemetría de sustituciones se anota en el asiento de cada completado; falta publicarla como métrica (ARG-059).
- El presupuesto se cuenta por tokens del backend; con el backend determinista esos números son un proxy por longitud, no tokens reales.
- La lista de identificadores es la española de ARG-024; otro país necesita sus validadores, no otra expresión regular.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-17 | Guardarraíles de entrada y salida, con las tablas como contenido | Fase 06 (ARG-060) |
| 0.1.0-alpha | 2026-09-17 | Gateway con colas, cuotas en tabla, JSON forzado, registro con hash y backend determinista | Fase 06 (ARG-052) |
| 0.1.0-alpha | 2026-09-17 | Corpus troceado por estructura jurídica e índice vectorial y léxico sobre pgvector | Fase 06 (ARG-053) |
| 0.1.0-alpha | 2026-09-17 | RAG normativo con recuperación híbrida, cita comprobada y rehúso honesto | Fase 06 (ARG-054) |
| 0.1.0-alpha | 2026-09-17 | Clasificación semántica con confianza calibrada por las decisiones del DPD | Fase 06 (ARG-055) |
| 0.1.0-alpha | 2026-09-17 | Generación asistida de retos que compilan antes de mostrarse, y rama de revisión en un worktree temporal | Fase 06 (ARG-056) |
| 0.1.0-alpha | 2026-09-17 | Dictámenes con cifras verificadas, veredictos intocables y marca de texto asistido | Fase 06 (ARG-057) |
| 0.1.0-alpha | 2026-09-17 | Asistente de consola con cuatro herramientas cerradas, presupuesto fijo y fuentes comprobadas | Fase 06 (ARG-058) |
| 0.1.0-alpha | 2026-09-17 | Arnés de evaluación con conjuntos dorados y puerta de calidad; embebedor de pruebas con señal y búsqueda léxica por cualquiera de las palabras | Fase 06 (ARG-059) |
| 0.1.0-alpha | 2026-09-17 | Servicio y contenedor del gateway en su propia red, con la sesión en el rol restringido y el diario abierto solo para añadir | Fase 06 (F06-13) |
| 0.1.0-alpha | 2026-09-21 | `POST /v1/assistant/ask`: el agente del asistente corre dentro del gateway con sus cuatro herramientas y solo viaja su resultado; `ModelUnavailableError` y `503` en ambos endpoints cuando el modelo local no contesta (hasta F06-05, siempre) | F08-08 |
