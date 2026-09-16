# Interfaces que exporta la Fase 03 (estado real en main)

Generada a partir del código de `main` al cerrar la Fase 3 (tag `fase-03`). Los nombres de código están en inglés (ADR-0005). Las desviaciones respecto al documento de fase están en `docs/desviaciones/ARG-021-023.md`, `ARG-024-025.md`, `ARG-026-028.md` y `ARG-029-030.md`.

| Componente | Interfaz | Consumidores |
|---|---|---|
| ARG-021 | `argos_inventory.graph.model`: vocabulario cerrado `NODE_LABELS` (10: `System`, `Schema`, `Table`, `Column`, `FileArea`, `Identity`, `Group`, `AISystem`, `Treatment`, `Category`), `EDGE_LABELS` (8: `CONTAINS`, `CAN_ACCESS`, `MEMBER_OF`, `FLOWS_TO`, `CLASSIFIED_AS`, `DECLARED_IN`, `USES_MODEL`, `OBSERVED`), `CATEGORIES` (9), `natural_key` y claves por etiqueta (`system_key`, `column_key`, `ai_system_key`…); `argos_inventory.graph.store.GraphStore(dsn)` con `query`, `execute` y `connection`; grafo AGE `inventory` (migraciones 0003 y 0008, índices GIN sobre `properties`) | Fases 4–8: todo el producto habla este vocabulario |
| ARG-022 | `argos_inventory.discovery`: `scan_system`, eventos `discovery.*.v1` con procedencia (`source_connector`, `probe_id`, `journal_seq`, `observed_at`); `argos.scan_runs` (0004); `argos_inventory.ingest.handlers.Ingestor` y el servicio `argos_inventory.ingest.main` (consumidor duradero `inventory-ingest`) | ARG-044 (sondas de campaña), consola |
| ARG-023 | `argos.inventory_deltas` y `compute_deltas` (evento `discovery.delta_ready.v1`, asiento `inventory.delta`); instantáneas inmutables `argos.inventory_snapshots` e `inventory_snapshot_nodes` (0005) con `take_snapshot`, `verify_snapshot` y `snapshot_nodes` | ARG-043 (retos sobre lo nuevo), Fase 5 (campañas contra instantánea), Fase 7 |
| ARG-024 | `argos_connector.validators` (DNI, NIE, NUSS, IBAN y `resolve_validators`); `classify_new_columns` con aristas `CLASSIFIED_AS {method, confidence, rate, validated}` | Fase 4 (aplicabilidad por categoría) |
| ARG-025 | `argos_inventory.classify.assisted`: `ClassificationModel` y `NullModel`, `argos.review_queue` (0006) y `decide_review` (asiento `inventory.review`) | Fase 6 (modelo real), consola (cola del DPO) |
| ARG-026 | `argos.catalog_columns`, `argos.catalog_coverage` y `argos.catalog_freshness` (0007) con `refresh_catalog`; `import_treatments` (nodos `Treatment`); `render_inventory_report` y `tools/inventory_report.py` | Hito de visado del inventario (P-26), retos art. 30 |
| ARG-027 | `argos_inventory.flows.detect`: `detect_engine_links` y `detect_structural`; aristas `FLOWS_TO {method, confidence, confirmed, evidence, last_seen}` y `System {external: true}` | Retos cap. V, consola |
| ARG-028 | `argos_inventory.ai_discovery.detect`: `discover_ai`, `provisional_register` y `confirm_ai_system` (asiento `inventory.ai_confirm`); nodos `AISystem {signals, confidence, status}` unidos con `USES_MODEL` | Familia de retos de gobierno de IA (Fase 5) |
| ARG-029 | API GraphQL `argos_inventory.api.app.create_app(store, validator)` en `/graphql` (desarrollo `127.0.0.1:8002`): `node(key, first, after)`, `resolveSelector(selector, first, after)` y `snapshot(id, first, after)`; selector con `ALLOWED_SELECTOR_FIELDS`, `MAX_PAGE_SIZE = 500` y `MAX_QUERY_DEPTH = 4`; basta cualquier rol del realm; sin mutaciones | ARG-042 (compilador de retos), Fase 4 (aplicabilidad), Fase 8 (consola) |
| ARG-030 | `argos_inventory.scheduler`: workflows `RescanPlanner` y `ScanSystem`, `InventoryActivities`, cola `argos-inventory` y Schedule `inventory-rescan-hourly` (política `SKIP`; en pausa en desarrollo) | ARG-094 (salud y carga), consola |
| Capacidad | `argos_inventory.benchmark` y `tools/inventory_benchmark.py` (perfiles `smoke`, `s` y `m`, base desechable `argos_bench_<hex>`) | Banco de integración de cada release (§3.10) |
| Pruebas | `tests/fixtures/inventory_ground_truth.yaml` y `ground_truth.py`; `tests/integration/inventory_helpers.py` (`RecordingBus`, `IngestingBus`, `scan_and_ingest`, `probe_runner`, `secret_store`); `tests/e2e/test_phase3_acceptance.py` | Fases 4–5 (verdad terreno de aplicabilidad) |

## Reglas de AGE 1.5.0 comprobadas

Detalle y sondas en `docs/desviaciones/ARG-021-023.md`.

- **Sin `MERGE … ON CREATE SET`:** se usa `SET x = coalesce(x, $now)`.
- **Patrones en `WHERE`:** `NOT exists((n)-[:X]->())`, no `WHERE NOT (n)-[:X]->()`.
- **Sin `reduce`:** los agregados (por ejemplo, la confianza de los candidatos de IA) se calculan en Python.
- **Parámetros:** el tercer argumento de `cypher()` tiene que ser un parámetro de psycopg (`%s`), nunca un literal.
- **Índices por clave natural:** `agtype_access_operator(VARIADIC ARRAY[properties, '"key"'::agtype])`, también como `UNIQUE`.
- **Lotes `UNWIND`:** nunca varias asignaciones con `coalesce` en una misma cláusula `SET` (dejó filas sin `first_seen`); una cláusula por propiedad o, mejor, un único `SET n += {mapa}` (F03-15). Nodos y aristas en sentencias separadas (si no, `vertex assigned to variable … was deleted`).
- **Nombres de columna del resultado:** entre comillas (`"table" agtype`), por las palabras reservadas de SQL.
- **Etiquetas:** AGE crea la tabla de cada etiqueta en la primera escritura; una vista o un índice sobre una etiqueta inexistente falla.
- **Migraciones que unen vértices y aristas:** necesitan `LOAD 'age'` y `SET LOCAL search_path = ag_catalog, "$user", public`.
- **`ORDER BY` (F03-12):** no admite alias del `RETURN` ni combinarse con `WITH DISTINCT`; la página se corta con `WITH DISTINCT n WITH n ORDER BY n.key LIMIT …` antes del `RETURN`, y el vecindario ordena por expresiones.
- **Propiedades en el patrón de una arista dentro de `MERGE`** (`-[f:FLOWS_TO {method: $method}]->`) sí funcionan (F03-10).
- **Índices que AGE usa (F03-15):** `MATCH`/`MERGE` con mapa de propiedades (`{key: $k}`) se planifica como contención sobre `properties` y **no usa** el btree sobre `agtype_access_operator(key)` de la migración 0003: recorría la etiqueta entera y dentro de `UNWIND` el coste era cuadrático. Tampoco basta `WHERE n.key = k` dentro de `UNWIND`. Un **índice GIN sobre `properties`** (migración `0008_graph_indexes.sql`) sí sirve la contención; el btree se conserva porque garantiza la clave única.
- **Sin recorridos de longitud variable en consultas calientes:** `[:CONTAINS*1..3]` desde un `System` tardaba 1,5 s por sistema con 10 200 columnas; preguntar por etiqueta con la propiedad indexada `{system_id: $sid}` tarda milisegundos. Un test puro vigila todas las consultas del inventario.
- **`SET n += {mapa}`** funciona en lotes `UNWIND` y escribe cada nodo una sola vez (16 ms frente a 114 ms con diez `SET` por fila), conservando las propiedades que no están en el mapa (`first_seen`).
- **`MERGE` de arista** recorre la tabla de aristas de la etiqueta (sin usar `start_id`/`end_id`): cuando se sabe que la arista es nueva, `CREATE` en una sentencia aparte (tras crear sus nodos) es plano con el tamaño del grafo.

## Resultados del benchmark

Coste propio de ARGOS (ingesta, deltas, clasificación por diccionario, instantánea y selector) sobre metadatos sintéticos, sin la latencia de las fuentes. Portátil Intel i7-1355U, 12 hilos, 15,7 GB, Windows 11, Python 3.12.10.

| Perfil | Tablas | Nodos | Tablas/s (base · reexploración) | Extrapolado a 50 000 tablas (completo · reexploración) | Selector p50 |
|---|---|---|---|---|---|
| `smoke` (F03-15) | 100 | 745 | 30,6 · 26,1 | — | 1,9 ms |
| `xs` (F03-15) | 1 000 | 11 269 | 18,1 · 19,6 | — | 13,7 ms |
| `s` antes (F03-14) | 5 000 | 55 659 | 1,5 · 0,9 | 9,5 h · 14,9 h | 59 ms |
| `s` después (F03-15) | 5 000 | 55 659 | 11,9 · 13,6 | **1,17 h · 1,02 h** | 62 ms |

- **Objetivos de §3.10** en esta máquina y por extrapolación: inventario completo (< 24 h), reexploración diaria (< 2 h) y selector (< 2 s) se cumplen tras F03-15. La cifra real se mide en el hardware del appliance (pendiente).
- **Cómo escala tras F03-15:** ya no quedan consultas con coste lineal en el tamaño del grafo. El coste por tabla crece de forma sublineal (unos 30, 51 y 74 ms de ingesta con 745, 11 269 y 55 659 nodos), y hay un coste fijo de unos 11 ms por evento al abrir conexión con `LOAD 'age'`.
- **Perfil `m`:** no se ha ejecutado en esta máquina.
