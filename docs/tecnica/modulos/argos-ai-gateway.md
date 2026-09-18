---
id: MOD-argos-ai-gateway
kind: module
title: Gateway de IA local (argos-ai-gateway)
module: argos-ai-gateway
phases: ["06"]
version: 0.1.0-alpha
commit: pendiente
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
- **Hará:** generación de retos (ARG-056), dictámenes (ARG-057), asistente con herramientas (ARG-058) y el arnés de evaluación (ARG-059).
- **No hace, y no es una cuestión de configuración:** emitir un veredicto. No hay ruta de importación, ni de red, ni de permisos de base de datos que lleve de aquí al evaluador.
- **No hace:** escribir en un sistema del cliente, ni proponer que se escriba.

## 3. Arquitectura

- **`argos_ai.guardrails`** (ARG-060): `scrub_input` a la entrada y `check_output` a la salida. Puro, sin modelo y sin entrada/salida, para poder probarlo entero.
- **`argos_ai.gateway.Gateway`** (ARG-052): la puerta. El diario y el registro de uso se inyectan, así que el gateway se ejerce entero sin base de datos; `argos_ai.quotas.postgres_gateway` lo monta como corre en el appliance.
- **`argos_ai.rag`** (ARG-053, ARG-054): troceado por estructura jurídica, embeddings, índice sobre pgvector y el pipeline de respuesta con cita obligatoria.
- **`argos_ai.classify`** (ARG-055): el clasificador semántico que rellena la interfaz ARG-025 de la Fase 03, con la confianza calibrada por las decisiones del DPD.
- **`argos_ai.backends`**: un contrato (`Backend`, `Completion`) y tres implementaciones. `OpenAiCompatibleBackend` sirve para vLLM y para llama.cpp, porque los dos hablan la misma API; `FakeBackend` responde desde un fichero indexado por el hash del prompt.
- Dependencias: `argos-common` (errores y configuración) y `argos-connector-sdk`, del que reutiliza los **validadores de identificadores españoles de ARG-024**.

### La barrera (F06-01)

Tres cierres, no una promesa escrita:

1. **Importaciones:** `tests/architecture/ai_boundary.py` sigue el grafo de importaciones real del espacio de trabajo y rechaza que cualquier módulo de este paquete alcance `argos_challenges.evaluator`, `.store` o `.findings`, aunque el cable esté atado tres módulos más allá.
2. **Permisos:** el rol `argos_ai` de PostgreSQL (migración `0015`) lee el esquema y escribe solo `argos.ai_usage`. Leer veredictos y hallazgos sí: redactar el informe desde ellos es el oficio de ARG-057.
3. **Red:** el contenedor no comparte red con la API de campañas (se comprueba en F06-13).

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

## 5. Configuración

`ARGOS_LLM_LOCAL_ENDPOINT` (desde la Fase 01) y `ARGOS_LLM_MODEL` (ADR-0009): dirección del servidor compatible OpenAI y nombre del modelo servido. Ningún módulo nombra un modelo. Los guardarraíles no necesitan configuración: sus tablas son contenido, y la cuota vive en `argos.ai_quotas`.

## 6. Seguridad y tratamiento de datos

- Ningún dato personal validado llega al modelo: se sustituye antes por un marcador.
- Ningún prompt se escribe en un log ni en una tabla; lo que se registra es su hash (ARG-052, `argos.ai_usage`).
- El paquete no puede escribir veredictos ni hallazgos, por código y por permisos.

## 7. Operación

El servicio aún no tiene contenedor propio; llega en F06-13, en su propia red.

## 8. Verificación

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

- El paquete está a medias: de los diez componentes están ARG-052, ARG-053, ARG-054, ARG-055 y ARG-060.
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
