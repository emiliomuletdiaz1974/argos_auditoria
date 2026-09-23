# ADR-0007 · Motor de retos y campañas: DSL, veredictos, campañas y sello (Fase 05)

**Estado:** Aceptado · 2026-09-17 · Aaron Escobar (con un cambio sobre la propuesta: capa de traducción en castellano para el DSL, como en ADR-0006) · **Sustituido en parte por ADR-0012** (2026-09-20): la API de campañas de `argos_challenges.api` se retiró en F08-17 y sus rutas viven en la API única `argos_api`; el resto sigue vigente.

## Contexto
La Fase 05 (ARG-041…050) construye el motor que comprueba: el DSL de retos, el compilador, los workflows de campaña, las actividades de sonda, el muestreo, el evaluador determinista, los puntos de control humanos, los hallazgos, la reejecución de subsanación y la biblioteca empaquetada. El Plan Director (§8.2, Fase 05) añade dos bloques que el documento de fase no desarrolla: el **sujeto sintético** (ADR-0008) y el **sello de campaña**.

El documento de fase asume piezas que no existen o que chocan con lo construido en las Fases 01–04:
- **Idioma:** claves y valores del DSL en castellano (`objetivo`, `sonda`, `criterio`, `umbral`, `operador`, `severidad: critica`, estados `abierto`, `en_resolucion`…), frente a ADR-0005 y a los ids en inglés del catálogo provisional de la Fase 04 (`sec-encryption-at-rest`, `ret-table-retention`…).
- **Infraestructura inexistente:** `argos_db.pool`, `argos.journal_append(...)` en SQL, `uuid.uuid7()` (Python 3.14), `inventory_client`, `connector_registry`, `opa_client` y `argos_auth.fastapi`, y un `services/api/routes` sin aplicación. La plataforma exporta `PostgresJournal`, `argos_common.ids.uuid7`, `GraphStore`, `open_connector`, `argos_ontology.opa.evaluate` y `argos_auth.validate`.
- **Veredicto binario:** el evaluador del documento solo emite `conforme` verdadero o falso. El Plan Director exige un tercer resultado: «no demostrado», con el tamaño de muestra necesario, cuando la cota de Wilson no permite absolver.
- **Contrato con OPA:** el evaluador lee `verdict["conforme"]` de paquetes `argos.retencion`; los paquetes reales de la Fase 04 son `argos.retention` y `argos.access` y devuelven `verdict.compliant`.
- **Roles:** el documento usa `revisor_dpo`; el realm de la Fase 01 define `dpo_reviewer`, `campaign_manager`, `read_only_auditor` y `platform_admin`.
- **Instantánea:** el Plan Director planifica sobre «perfil normativo + instantánea», y la prueba de la fase exige que reejecutar con la misma instantánea dé los mismos veredictos. El documento resuelve nodos contra el grafo vivo.
- **Sello:** el documento lanza `seal_campaign_act` como parte de la Fase 07, pero la prueba de la Fase 05 exige que «el sello verifica».
- **Vector de muestreo erróneo:** con sus propias fórmulas, `sample_size(10_000, 0.95, 0.05)` da 370, no 371.

## Decisión
- **DSL de retos:**
  - YAML validado con **JSON Schema 2020-12** mediante la librería `jsonschema`, en CI y en carga;
  - **claves y valores en inglés en el núcleo** (`objective`, `selector`, `probe`, `criterion`, `threshold`, `evidence`, `severity`, `sampling`, `approval_required`): el esquema, el lint, el compilador y el evaluador solo conocen el inglés (ADR-0005);
  - **capa de traducción en castellano** (`argos_challenges.library.translation`), como la de la plantilla editorial de ADR-0006:
    - quien edita un reto puede usar las claves en castellano (`objetivo`, `sonda`, `criterio`, `umbral`, `evidencia`, `severidad`, `muestreo`, `aprobacion_requerida`…) y los valores enumerados en castellano (`critica`, `recuentos`…);
    - la capa los traduce a inglés con una tabla cerrada y biyectiva antes de validar, y de vuelta al generar un reto para editar;
    - una clave o un valor fuera de la tabla es un error, nunca se ignora;
    - tiene tests propios de ida y vuelta, claves desconocidas y claves duplicadas;
  - `title` es texto libre en castellano;
  - los **ids son los del catálogo** de la Fase 04 y las severidades las de la ontología (`critical`, `high`, `medium`, `low`);
  - campos opcionales del modelo de reto del Plan Director: `preconditions` (por ejemplo, un sujeto sintético inyectado) y `estimated_cost` (sondas y filas previstas).
- **Veredicto de cuatro valores:**
  - `compliant`;
  - `non_compliant`;
  - `not_demonstrated`: la muestra no permite absolver, y se indica el `n` necesario;
  - `inconclusive`: la sonda falló; no abre hallazgo, pero queda en el expediente.
- **Evaluador puro y único:**
  - `argos_challenges.evaluator.evaluate(unit, probe_result, decision)` es una función pura, sin E/S ni reloj;
  - la actividad hace la E/S: consulta OPA antes y persiste después;
  - el veredicto se serializa con la canonización del diario v1 (`argos_common.journal.canonicalize`) y lleva `verdict_hash`;
  - un test arquitectónico impide que otro módulo construya veredictos o escriba en `argos.verdicts`.
- **Contrato OPA:** todo paquete usado como criterio expone `verdict.compliant` (booleano) más sus campos explicativos; el reto declara el paquete y el `input_map`.
- **Campaña reproducible:**
  - la campaña **fija** una instantánea del inventario (`take_snapshot`), la versión de ontología vigente y la versión de la biblioteca;
  - el plan se resuelve sobre la instantánea con un `SelectorResolver` de instantánea, con el protocolo de F04-11;
  - dos ejecuciones con la misma instantánea y los mismos resultados de sonda producen los mismos `verdict_hash`.
- **Temporal:**
  - workflows `CampaignWorkflow` y `SystemRun` en la cola existente `argos-campaigns` (F1-08), sin E/S en los workflows;
  - actividades con `open_connector`, `LoadBudget` y `QueryJournal` de las Fases 02 y 03;
  - `wait_window` como espera con heartbeat, no como fallo;
  - el worker tiene contenedor en el entorno de desarrollo.
- **API de campañas:** servicio FastAPI en `argos_challenges.api` (planificar, lanzar, estado, resultados y aprobaciones), con `argos_auth`:
  - `campaign_manager` planifica y lanza;
  - `dpo_reviewer` aprueba, con doble control configurable para el muestreo.
- **Hallazgos:** estados en inglés (`open`, `in_remediation`, `pending_verification`, `closed_compliant`, `reopened`, `risk_accepted`), deduplicación por huella y escalado por recurrencia; los asientos van al diario con `PostgresJournal` y los eventos se publican con `argos_events`.
- **Sello de campaña en la Fase 05:**
  - asiento `campaign.seal` con el SHA-256 canónico de los `verdict_hash` ordenados, el hash de la instantánea, la versión de ontología y el hash del bundle de la biblioteca;
  - `verify_seal` lo recalcula;
  - la Fase 07 añade Merkle, firma y anclaje de cabeza (ARG-066) sin cambiar lo que se sella.
- **Biblioteca:**
  - `library/challenges/<family>/<id>.yaml` y `library/challenges/archive/<version>/` congelado en cada publicación, dentro del bundle firmado de ARG-040;
  - el catálogo `catalog.yaml` se **genera** desde los retos y una puerta comprueba que está al día.
- **Migraciones:** a partir de `0011`, para campañas, veredictos, solicitudes de aprobación, aprobaciones, hallazgos y sujetos sintéticos (ADR-0008).

## Consecuencias
- Nueva dependencia: `jsonschema`.
- ADR-0005 se cumple sin excepciones: el castellano del DSL vive solo en la capa de traducción. `fastapi`, `httpx`, `temporalio` y `psycopg` ya están en el workspace.
- Un contenedor más en `make dev`: el worker de campañas. Resuelve el pendiente abierto en F1-08.
- La prueba de la fase se vuelve reproducible por construcción: los veredictos dependen de la instantánea fijada y de resultados de sonda capturados, no del reloj ni del grafo vivo.
- El expediente de la Fase 07 recibe veredictos ya canónicos y un sello verificable que solo tendrá que envolver.
- Los 27 retos del catálogo provisional se escriben en el DSL con sus ids actuales; los ejemplos `ret-001` y `sec-cifrado-reposo` del documento pasan a `ret-table-retention` y `sec-encryption-at-rest`.

## Alternativas descartadas
- **DSL con gramática propia:** coste de herramienta alto y sin validación gratuita; el documento de fase ya lo descarta.
- **DSL solo en inglés, sin capa de traducción** (propuesta inicial): rechazada en la aprobación del 2026-09-17; los retos se editan también en castellano, como la plantilla editorial.
- **Veredicto binario del documento:** con muestras insuficientes absuelve o condena sin base estadística, en contra del Plan Director.
- **Sello solo en la Fase 07:** la prueba de la Fase 05 quedaría sin su criterio «el sello verifica».
- **Resolver contra el grafo vivo:** dos ejecuciones con la misma campaña no serían comparables.
