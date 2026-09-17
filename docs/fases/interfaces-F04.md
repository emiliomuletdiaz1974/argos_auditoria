# Interfaces que exporta la Fase 04 (estado real en main)

Generada a partir del código de `main` en el **cierre técnico** de la Fase 4 (tag `fase-04-tecnica`). Los nombres de código están en inglés (ADR-0005). Las decisiones aplicables son ADR-0006 y las notas de desviación `docs/desviaciones/ARG-031-033.md` y `ARG-034-040.md`.

> **Contenido normativo pendiente de validación jurídica.** Las poblaciones RGPD, EHDS y AI Act, la verdad terreno de aplicabilidad y las decisiones del DPO sintético de la demostración están estructuradas técnicamente, pero no validadas. Las interfaces de código de esta tabla son estables; el contenido de la biblioteca puede cambiar al validarse, y entonces se crea el tag `fase-04`.

| Componente | Interfaz | Consumidores |
|---|---|---|
| ARG-031 | `argos_ontology.vocabulary`: espacios de nombres `ARGOS`, `NORMS`, `DPV`, `ELI` y `ODRL`; vocabulario cerrado `CLASSES`, `OBJECT_PROPERTIES`, `DATATYPE_PROPERTIES`, `SEVERITIES` y `EVIDENCE_TYPES`; `LIBRARY_DIR`, `ONTOLOGY_VERSION = "1.0.0"`, `bind_prefixes` y `load_core`; núcleo `library/ontology/core/argos-core.ttl` | Fase 5 (retos por obligación), Fase 7 (evidencia) |
| ARG-032 | Migración `0009_ontology.sql` (`argos.ontology_bundles`, `argos.ontology_quads`, inmutables); `argos_ontology.store`: `store_version`, `version_in_force`, `bundle_record`, `OntologyStore(dsn, version=None, at=None)` con `sparql` y `graph`, `BundleConflictError`; asiento `ontology.load` | Fase 5 (campañas contra la versión vigente), Fase 8 (consola) |
| ARG-033 | `library/ontology/asset-classes/base.ttl` (11 clases, entre ellas `AC-confirmed-ai-system`); `argos_ontology.applicability`: `load_asset_classes`, `asset_classes`, `compiled_selector` y `asset_class_errors`; selector de la API del inventario ampliado con `unclassified` y `status` | ARG-039, ARG-042 (compilador de retos) |
| ARG-034 | `library/ontology/shapes/inventory-coherence.ttl`; `argos_ontology.shacl`: `export_graph`, `load_shapes`, `validate_graph`, `run_shapes` y `ShapeFinding(node, shape, message, severity)` | Retos `coh-*` (Fase 5) |
| ARG-035 | `argos_ontology.odrl`: `parse_policy`, `to_challenges`, `duration_days`, tipos `Policy`, `Rule`, `Constraint` y `PolicyError`; plantillas `ds-asset-retention`, `ds-usage-purpose`, `ds-no-redistribution` y `ds-unverifiable` | Retos de espacios de datos (Fase 5) |
| ARG-036 | `library/policies/retention.rego` y `access.rego` (paquetes `argos.retention` y `argos.access`, cada uno con `verdict`); `argos_ontology.opa.evaluate(package, input_doc, base_url)` y `OpaError`; contenedor `opa` 1.20.2 en `127.0.0.1:8181`; datos del cliente en `data.client`; `make policy-test` | Evaluador de retos `ret-*` y `acc-*` (Fase 5) |
| ARG-037 | `library/challenges/catalog.yaml` (catálogo provisional); `argos_ontology.traceability`: `library_graph`, `load_challenge_catalog`, `build_matrix`, `matrix_json` y `matrix_csv`; `tools/ontology_traceability.py` | **Fase 5: implementar los 27 retos con los mismos ids**; supervisor (matriz) |
| ARG-038 | Plantilla editorial en castellano y capa de traducción (`argos_ontology.editorial.translation`); compilador determinista (`argos_ontology.editorial.compiler`: `parse_obligation`, `compile_obligation`, `compile_file`) y `tools/ontology_compile.py [--check]`; cinco puertas (`argos_ontology.gates.run_gates`, `GATE_NAMES`) con `make ontology-gates` en CI; matriz de solapamiento (`argos_ontology.overlap`: `build_overlap`, `overlap_json`, `overlap_csv`) con `make ontology-overlap`; proceso editorial en `docs/ontologia/proceso-editorial.md` | Equipo editorial, CI |
| ARG-039 | Migración `0010_applicability.sql` (`argos.applicability_runs`, inmutable); `argos_ontology.resolver`: `resolve(dsn, ontology, selectors, scope, campaign_id=None, bus=None, at=None)`, `requirements`, `build_plan`, `check_scope`, `in_force`, protocolo `SelectorResolver` y `StoreSelectorResolver`; asiento `applicability.resolve`; evento `challenge.applicability_ready.v1` en `argos.challenge.applicability_ready` | **ARG-041 (motor de campañas)**, Fase 8 (plan en la consola) |
| ARG-040 | `argos_ontology.bundle`: `build_bundle` (tar.gz determinista), `sign_bundle`, `verify_bundle`, `bundle_graph`, `load_bundle` y `BundleRejectedError`; clave Vault Transit `argos-content` (Ed25519, no exportable); `tools/ontology_publish.py build` y `verify` | Actualización de contenidos del appliance (Fase 10) |
| Clasificación (Fase 3, ampliada en F04-21 y F04-22) | `argos_inventory.classify.dictionary`: referencias a paciente como `personal_data`, categorías especiales no sanitarias como `special_category.other`, `match_column_in_table` y método `dict:table` para puntuaciones de tablas clínicas; `SCORE_TOKENS` compartido con el descubrimiento de IA | Aplicabilidad, Fase 6 (clasificador asistido) |
| Pruebas | `tests/fixtures/applicability_ground_truth.yaml` y `.py` (`load_applicability_truth`, `expected_plan`); `tests/fixtures/demo_review.yaml` y `.py` (`apply_demo_review`); `tests/e2e/test_phase4_acceptance.py` | Fase 5 (campañas sobre la instantánea de demostración), F04-98 |

## Reglas comprobadas

- **rdflib 7.6:** el Turtle generado es byte a byte idéntico con la misma entrada (ordenación estable de tripletas y prefijos fijos). Las consultas SPARQL con `initBindings` tipados no admiten inyección de texto.
- **Almacén RDF en PostgreSQL:** las cuádruplas se guardan en N3 con `COPY` y los triggers impiden `UPDATE`, `DELETE` y `TRUNCATE`. La versión vigente se decide por `in_force_from`, no por el orden de carga.
- **pySHACL 0.40:** la validación se hace sobre una exportación RDF del grafo AGE, nunca sobre AGE directamente. Los mensajes para el DPO salen de `sh:message` de la forma.
- **OPA 1.20.2:**
  - el servidor carga los datos por ruta (`/data/client/data.json` → `data.client`) e ignora los `*_test.rego`;
  - `not x in lista` es indefinido si falta el campo, y por eso se usa `object.get`;
  - sin `--watch`, porque los montajes de Windows no propagan eventos.
- **tar determinista:** miembros ordenados, `mtime`, `uid`, `gid` y modo fijos, y gzip con `mtime=0`. El manifiesto con SHA-256 de cada miembro se firma con Ed25519 en Vault Transit, y el bundle se verifica **antes** de tocar el almacén.
- **Vigencia:** una obligación aplica si `inForceFrom ≤ fecha < inForceUntil`, con la fecha de la campaña y nunca con la de carga de la ontología.

## Cifras de la biblioteca v1 (pendiente de validación jurídica)

| Norma | Obligaciones | Con reto | Pendientes de verificación | Aplicable desde |
|---|---|---|---|---|
| RGPD | 13 | 12 | 1 (`OBL-RGPD-33-1`, simulacro de brecha) | 2018-05-25 |
| EHDS | 7 | 6 | 1 (`OBL-EHDS-60-1`, organismo de acceso) | 2029-03-26 |
| AI Act | 8 | 8 | 0 | 2025-02-02 (art. 5) y 2026-08-02 |
| **Total** | **28** | **26** | **2** | |

- **Catálogo provisional:** 27 retos, sin huérfanos.
- **Requisitos (obligación × clase de activo × reto) de la biblioteca por fecha:** 43 a 1-3-2025, 50 a 16-9-2026 y 56 a 26-3-2029.
- **Plan sobre la instantánea de demostración:** 49 filas a 16-9-2026 y 55 a 26-3-2029. Las clases sin nodos no generan fila.
- **Solapamiento entre normas:** 1 clase de activo, `AC-stored-health-data` (RGPD y EHDS).
