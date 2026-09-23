---
id: MOD-argos-inventory
kind: module
title: Inventario y grafo de conocimiento (argos-inventory)
module: argos-inventory
phases: ["03", "04"]
version: 0.1.0-alpha
commit: e3c4910
date: 2026-09-17
status: current
confidentiality: client
---

# Inventario y grafo de conocimiento (argos-inventory)

## 1. Propósito

Construye y mantiene el **inventario vivo** de los sistemas del cliente en un grafo de conocimiento: sistemas, esquemas, tablas, columnas, repositorios de ficheros, identidades, grupos, tratamientos y sistemas de IA. También registra qué categoría de dato contiene cada columna, cómo fluyen los datos entre sistemas y qué ha cambiado desde la última exploración. Implementa ARG-021 a ARG-030.

## 2. Alcance y límites

- Se alimenta exclusivamente de las sondas de solo lectura de los conectores (ver `argos-connector-sdk`); nunca accede directamente a los sistemas del cliente.
- La clasificación asistida por modelo tiene hoy su interfaz y su cola de revisión humana. El modelo real se incorpora con la IA local (Fase 06).
- El inventario describe estructura y metadatos. Las muestras solo se usan para validar identificadores en origen y nunca se almacenan en claro.

## 3. Arquitectura

| Componente | Paquete | Qué hace |
|---|---|---|
| Modelo del grafo (ARG-021) | `graph` | Vocabulario cerrado: 10 etiquetas de nodo, 8 de arista y 9 categorías de dato; claves naturales; `GraphStore` sobre PostgreSQL y Apache AGE |
| Escáner (ARG-022) | `discovery` | Traduce las sondas de los conectores en eventos `DISCOVERY` con procedencia (conector, sonda, asiento del diario, momento); registro de exploraciones |
| Ingesta (ARG-022) | `ingest` | Consumidor duradero del stream `DISCOVERY` que escribe el grafo de forma idempotente y en lotes |
| Versionado (ARG-023) | `versioning` | Deltas entre exploraciones (aparecido, desaparecido, crecimiento anómalo) e **instantáneas inmutables** verificables |
| Clasificación determinista (ARG-024) | `classify` | Diccionario de nombres por palabras completas, contexto de tabla para inferencias clínicas y validación de identificadores en origen (DNI, NIE, NUSS, IBAN, NHC) |
| Clasificación asistida (ARG-025) | `classify.assisted` | Interfaz de modelo y **cola de revisión** del DPD con decisión auditada. Desde la Fase 06 el modelo es `argos_ai.classify.SemanticClassifier` (ARG-055), que entrega la confianza ya calibrada; la interfaz no cambió. Una propuesta `no_personal_data` va siempre a la cola, por alta que sea su confianza: sacaría la columna de los selectores de todas las campañas, y los nombres de columna que llevan a ella vienen del sistema del cliente |
| Catálogo (ARG-026) | `catalog` | Vistas de catálogo, cobertura y frescura; importación del registro de tratamientos; informe legible del inventario |
| Flujos (ARG-027) | `flows` | Detección de flujos entre sistemas por catálogo del motor (enlaces de base de datos) y por coincidencia estructural |
| IA (ARG-028) | `ai_discovery` | Descubrimiento de candidatos a sistema de IA (columnas de puntuación, ficheros de modelo); confirmación humana con clase de riesgo |
| API (ARG-029) | `api` | API GraphQL de solo lectura con selector restringido y paginación |
| Planificador (ARG-030) | `scheduler` | Reexploración priorizada con Temporal |
| Capacidad | `benchmark` | Banco de pruebas reproducible de rendimiento |

**Reglas del clasificador determinista** (confianza 0,6 para el diccionario y 1,0 para un validador aceptado):
- **Diccionario (`dict`):** secuencias de palabras completas del nombre de la columna, en castellano e inglés, nunca subcadenas.
  - Desde la Fase 04, las referencias a un paciente (`patient_id`, `patient_ref`, `paciente_id`, `id_paciente`) son `personal_data`: un identificador seudonimizado sigue siendo dato personal (RGPD, considerando 26).
- Desde la Fase 04 también se reconocen **categorías especiales distintas de la salud** (`special_category.other`): afiliación sindical, religión, origen étnico, orientación sexual, datos biométricos y genéticos (RGPD, art. 9.1).
- **Contexto de tabla (`dict:table`, Fase 04):** una columna de puntuación (`score`, `pred`, `prediction`, `probability`, `propensity`) en una tabla de inferencias clínicas (`readmission`, `reingreso`, `mortality`, `mortalidad`, `sepsis`, `triage`, `triaje`) es `special_category.health`.
  - Una inferencia sobre la salud es dato de salud (RGPD, art. 4.15).
  - La misma puntuación en otra tabla, por ejemplo un riesgo de crédito, queda sin clasificar.
- **Validadores en origen (`validator:<nombre>`):** ganan al diccionario cuando la tasa de aceptación alcanza 0,9.
- Estas reglas están **pendientes de validación jurídica**.

Dependencias: `argos-common`, `argos-events`, `argos-auth`, `argos-connector-sdk` y los conectores; PostgreSQL 16 con Apache AGE 1.5.0; NATS JetStream; Temporal.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Grafo | `inventory` (AGE) | Nodos `System`, `Schema`, `Table`, `Column`, `FileArea`, `Identity`, `Group`, `AISystem`, `Treatment` y `Category`; aristas `CONTAINS`, `CAN_ACCESS`, `MEMBER_OF`, `FLOWS_TO`, `CLASSIFIED_AS`, `DECLARED_IN`, `USES_MODEL` y `OBSERVED` |
| Eventos | `discovery.*.v1`, `discovery.ingested.v1`, `discovery.delta_ready.v1` | Descubrimiento, ingesta confirmada y deltas listos |
| Tablas | `argos.scan_runs`, `inventory_deltas`, `inventory_snapshots`, `inventory_snapshot_nodes`, `review_queue`, `catalog_columns`, `catalog_coverage` y `catalog_freshness` | Migraciones `0003` a `0008`; desde la Fase 05, los nodos de instantánea guardan también `status` (migración `0013`) |
| Funciones | `scan_system`, `compute_deltas`, `take_snapshot`, `verify_snapshot`, `classify_new_columns`, `decide_review`, `refresh_catalog`, `import_treatments`, `detect_engine_links`, `detect_structural`, `discover_ai` y `confirm_ai_system` | Operaciones del inventario |
| API GraphQL | `/graphql`: `node(key, first, after)`, `resolveSelector(selector, first, after)` y `snapshot(id, first, after)` | Solo lectura; sin mutaciones |
| Herramientas | `tools/inventory_report.py` y `tools/inventory_benchmark.py` | Informe del inventario y banco de capacidad |
| Procesos | `python -m argos_inventory.ingest.main`, `...api.main` y `...scheduler.worker` | Ingesta (consumidor `inventory-ingest`), API (desarrollo `127.0.0.1:8002`) y planificador (cola `argos-inventory`) |

## 5. Configuración

- Variables comunes de `argos-common`: base de datos, NATS, Temporal, OIDC y Vault para los servicios que abren conectores.
- **Parámetros de la API:**
  - página máxima de 500 elementos;
  - profundidad máxima de consulta 4, como mucho 10 alias y 1000 tokens por petición: la profundidad sola no acota una consulta, porque cada alias de `node` es otra búsqueda en el grafo;
  - los errores de validación y de argumentos llegan al cliente, pero una excepción de un resolver responde «Unexpected error.» y no describe la base de datos ni AGE;
  - campos del selector limitados a una lista cerrada (`ALLOWED_SELECTOR_FIELDS`): `label`, `category`, `min_confidence`, `missing`, `name_like`, `system_kind` y, desde la Fase 04, `unclassified` (columnas con o sin clasificación; no se combina con `category`) y `status` (prefijo del estado, por ejemplo sistemas de IA `pending` o `confirmed`).
- **Parámetros del planificador:**
  - cadencia estructural de 24 h;
  - hasta 4 exploraciones en paralelo;
  - prioridad por antigüedad, deltas recientes y candidatos de IA pendientes.

## 6. Seguridad y tratamiento de datos

- **Procedencia:** cada hecho del grafo es trazable hasta la sonda, el conector y el asiento del diario de consultas que lo produjo.
- **Decisiones humanas auditadas:** las revisiones de clasificación y la confirmación de sistemas de IA quedan en el diario encadenado (`inventory.review`, `inventory.ai_confirm`). Un sistema de IA solo se confirma con una clase de riesgo válida y una persona identificada.
- **Instantáneas inmutables:** una instantánea no cambia aunque el grafo vivo sí, y `verify_snapshot` comprueba su integridad. Es la base de campañas reproducibles.
- **API de solo lectura:** requiere un token válido del realm con cualquiera de sus roles. El selector no admite texto libre en la consulta: los valores viajan como parámetros y las etiquetas salen del vocabulario cerrado.
- **Minimización:** la validación de identificadores produce tasas de aceptación, no valores.
- **Decisiones aplicables:** notas de desviación ARG-021-023, ARG-024-025, ARG-026-028 y ARG-029-030.

## 7. Operación

- Tres procesos: ingesta, API y worker del planificador.
- El Schedule de Temporal `inventory-rescan-hourly` se crea con la política de solapamiento `SKIP`. En desarrollo está en pausa y se reactiva en el despliegue.
- **Capacidad medida** en un portátil de desarrollo (Intel i7-1355U, 15,7 GB), coste propio de ARGOS sin la latencia de las fuentes, perfil de 5000 tablas:
  - 11,9 tablas/s en la exploración inicial y 13,6 en la reexploración;
  - extrapolado a 50 000 tablas: 1,17 h el inventario completo y 1,02 h la reexploración (objetivos: menos de 24 h y menos de 2 h);
  - mediana de 62 ms en el selector (objetivo: menos de 2 s).
  - La cifra definitiva se mide en el hardware del appliance.

## 8. Verificación

- **Tests unitarios** en `services/inventory/tests`, entre ellos uno que vigila que ninguna consulta del inventario tenga coste lineal en el tamaño del grafo.
- **Tests de integración** `tests/integration/test_inventory_*.py`: grafo, escáner, ingesta, versionado, clasificación, catálogo, informe, flujos, IA, GraphQL, planificador, verdad terreno y benchmark; además, `test_graph_performance.py`.
- **Prueba de la Fase 03:**
  - el inventario de las fuentes simuladas coincide **exactamente** con la verdad terreno mantenida a mano;
  - los cambios provocados producen exactamente los deltas esperados;
  - la instantánea previa sigue íntegra y servida igual por la API.

## 9. Limitaciones conocidas y pendientes

- **Capacidad** en el hardware real del appliance (perfil `m`): sin medir.
- **Remuestreo de contenidos** con IA local: Fase 06.
- **Detectores basados en registros** y en inventarios de paquetes: aplazados.
- **Schedule de reexploración:** en pausa en desarrollo.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-16 | Inventario, grafo, versionado, clasificación, catálogo, flujos, IA, API GraphQL y planificador | Fase 03 (ARG-021…030) |
| 0.1.0-alpha | 2026-09-16 | Índices GIN, consultas por etiqueta y escrituras en lote: la reexploración extrapolada pasa de 14,9 h a 1,02 h | Fase 03 (rendimiento) |
| 0.1.0-alpha | 2026-09-17 | Selector ampliado con `unclassified` y `status` para el plano de aplicabilidad de la ontología | Fase 04 (ARG-033) |
| 0.1.0-alpha | 2026-09-17 | Clasificador: referencias a pacientes como dato personal y puntuaciones de tablas clínicas como dato de salud (`dict:table`) | Fase 04 (ARG-024) |
| 0.1.0-alpha | 2026-09-17 | Las instantáneas proyectan el `status` de los nodos, que necesita la resolución de campañas | Fase 05 (ARG-042) |
| 0.1.0-alpha | 2026-09-17 | Diccionario de categorías especiales no sanitarias y tabla sintética `clinic.staff_affiliations` en la fuente de desarrollo | Fase 04 (ARG-024) |
| 0.1.0-alpha | 2026-09-17 | La interfaz de ARG-025 tiene servicio: el clasificador semántico calibrado de la Fase 06, sin cambios en la cola ni en los umbrales | Fase 06 (ARG-055) |
| 0.1.0-alpha | 2026-09-18 | El modelo no puede aceptar solo una propuesta `no_personal_data`: siempre la revisa el DPD | Auditoría de seguridad (M8) |
| 0.1.0-alpha | 2026-09-18 | La API GraphQL limita alias y tokens por petición y enmascara los errores internos | Auditoría de seguridad (M9, B7) |
| 0.1.0-alpha | 2026-09-20 | Lectores para la API v1: `catalog.views.systems`, `pending_review_by_system`, `classify.assisted.pending_reviews` y `graph.reads.node_detail` (el Cypher del vecindario deja de vivir en el esquema GraphQL y se comparte) | Fase 08 (ARG-074) |
| 0.1.0-alpha | 2026-09-21 | `decide_review(..., corrected_to=...)`: una corrección es un rechazo para la calibración y una clasificación humana con la categoría elegida; `versioning.deltas.node_deltas` para la línea temporal de un nodo | F08-11 |
