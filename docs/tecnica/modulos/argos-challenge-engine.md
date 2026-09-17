---
id: MOD-argos-challenge-engine
kind: module
title: Motor de retos y campañas (argos-challenge-engine)
module: argos-challenge-engine
phases: ["01"]
version: 0.1.0-alpha
commit: c33466d
date: 2026-09-17
status: draft
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

## 5. Configuración

`ARGOS_TEMPORAL_ADDRESS` y `ARGOS_DATABASE_URL` (para el diario), desde `argos-common`.

Dependencias: `argos-common`, `argos-ontology`, el SDK de Temporal, `jsonschema` 4.23 y PyYAML.

## 6. Seguridad y tratamiento de datos

- Cada actividad que produce un resultado relevante lo anota en el diario de auditoría encadenado.
- El workflow de humo no accede a sistemas del cliente.

## 7. Operación

- Temporal en desarrollo en `127.0.0.1:7233`.
- El worker se arranca con `uv run python -m argos_challenges.worker`; aún no tiene contenedor propio en el entorno de desarrollo (ver §9).

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

## 9. Limitaciones conocidas y pendientes

- El motor de retos completo se construye en la Fase 05.
- El worker no tiene contenedor en `deploy/dev/compose.yaml` (pendiente para la Fase 05).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Worker de Temporal con workflow de humo, reintentos y asientos en el diario | Fase 01 (ARG-007) |
| 0.1.0-alpha | 2026-09-17 | Incumplimientos plantados y verdad terreno de campaña para la prueba de la Fase 05 | Fase 05 (F05-01) |
| 0.1.0-alpha | 2026-09-17 | Vectores de muestreo y cota de Wilson calculados a mano | Fase 05 (F05-02) |
| 0.1.0-alpha | 2026-09-17 | Suite de determinismo del veredicto con bytes canónicos esperados | Fase 05 (F05-03) |
| 0.1.0-alpha | 2026-09-17 | Test arquitectónico de la frontera de veredictos | Fase 05 (F05-04) |
| 0.1.0-alpha | 2026-09-17 | DSL de retos con esquema, capa de traducción en castellano, lint y retos patrón | Fase 05 (ARG-041) |
