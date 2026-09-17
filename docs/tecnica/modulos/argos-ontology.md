---
id: MOD-argos-ontology
kind: module
title: Ontología normativa (argos-ontology)
module: argos-ontology
phases: ["04"]
version: 0.1.0-alpha
commit: ce7ccb3
date: 2026-09-17
status: draft
confidentiality: client
---

# Ontología normativa (argos-ontology)

> Documento en construcción durante la Fase 04: cada tarea de la fase añade su componente. Pasa a `current` con el cierre de la fase.

## 1. Propósito

Convierte la normativa (RGPD, EHDS, AI Act) en **datos verificables**. Cada obligación queda descrita con:
- el artículo del que deriva;
- los activos del inventario a los que aplica;
- los retos que la verifican;
- el tipo de evidencia que producen.

Implementa ARG-031 a ARG-040. Este documento cubre por ahora ARG-031 (núcleo), ARG-032 (almacén versionado) y el flujo editorial de ARG-038.

## 2. Alcance y límites

- Describe obligaciones, su aplicabilidad y su verificación; no ejecuta verificaciones (eso es del motor de retos, Fase 05).
- Ninguna obligación se presenta como validada hasta su revisión por el perfil jurídico-técnico.

## 3. Arquitectura

### Núcleo de tres planos (ARG-031)

| Plano | Clases | Propiedades principales |
|---|---|---|
| Normativo | `Norm`, `Article`, `Obligation` | `derivesFrom`, `partOf`, `supersedes`, `equivalentTo` (simétrica), `eli`, `inForceFrom`, `inForceUntil`, `severity`, `verificationPending` |
| Aplicabilidad | `AssetClass` | `appliesTo`, `dataCategory`, `graphLabel`, `selectorJson` |
| Verificación | `Challenge`, `Verification`, `EvidenceType` | `verifiedBy`, `evidenceType`, `challengeId` |

- **Tipos de evidencia**, lista cerrada: `query_result`, `configuration`, `log_extract` y `document`.
- **Severidades:** `critical`, `high`, `medium` y `low`.

El núcleo se publica como contenido (`library/ontology/core/argos-core.ttl`, OWL en Turtle). Su espejo en código es `argos_ontology.vocabulary`, y un test mantiene ambos alineados.

### Flujo editorial (ARG-038)

El jurista redacta cada obligación en una **plantilla YAML en castellano** (`library/ontology/editorial/<OBL-ID>.yaml`) sin escribir Turtle. El recorrido hasta el grafo es este:

1. **Lectura estricta** (`translation.read_editorial`): YAML seguro que rechaza claves repetidas.
2. **Capa de traducción** (`translation.to_internal`): convierte las claves en castellano (`norma`, `articulo`, `titulo`, `vigente_desde`, `severidad`, `texto_resumen`, `aplica_a`, `verificado_por`, `equivalencias`, `pendiente_verificacion`) en las claves internas en inglés, con una tabla cerrada y biyectiva. Una clave desconocida es un error. Así el núcleo nunca ve claves en castellano (ADR-0005 y ADR-0006).
3. **Validación estricta** (`compiler.parse_obligation`): campos obligatorios, identificadores con formato (`OBL-…`, norma, artículo, clases `AC-…`, retos y equivalencias), severidad de la lista cerrada y fecha de vigencia sin hora.
4. **Generación con rdflib** (`compiler.obligation_graph`): el Turtle se construye con rdflib, nunca concatenando texto, y se serializa de forma canónica: **el mismo YAML produce siempre los mismos bytes**.

La herramienta `tools/ontology_compile.py` genera `library/ontology/norms/generated/<OBL-ID>.ttl`, y con `--check` falla si algún Turtle generado falta o está desfasado.

**Convenciones de nombres:**

| Elemento | Nombre |
|---|---|
| Obligación | `OBL-<NORMA>-<artículo>-<n>` |
| Artículo | `n:<NORMA>-<artículo con guiones>` |
| Reto | `n:CH-<id del catálogo>` |
| Equivalencia | `n:<MARCO>-<código con guiones>` |

### Almacén versionado (ARG-032)

Cada versión publicada de la ontología se guarda **una sola vez y para siempre** en PostgreSQL (migración `0009_ontology.sql`):
- **`argos.ontology_bundles`:** versión `MAJOR.MINOR.PATCH`, SHA-256 del bundle, manifiesto, firma, número de tripletas, fecha de entrada en vigor y fecha de carga.
- **`argos.ontology_quads`:** las tripletas de cada versión en forma N3, de modo que el grafo se reconstruye exactamente.
- **Inmutabilidad:** unos triggers impiden actualizar, borrar o truncar ambas tablas.

Funcionamiento:
- **Versión vigente:** la vigente en una fecha es la de `in_force_from` más reciente que no sea posterior a esa fecha. Esa fecha sale del manifiesto firmado, nunca de la hora de carga. Así, cargar tarde un bundle antiguo no cambia qué ontología aplicaba en el pasado.
- **Carga idempotente:** cargar dos veces el mismo contenido no hace nada; la misma versión con otro contenido se rechaza (`BundleConflictError`).
- **Auditoría:** cada carga deja el asiento `ontology.load` en el diario encadenado.
- **Consultas:** `OntologyStore` ejecuta SPARQL en proceso sobre una versión concreta o la vigente en una fecha. Los parámetros de las consultas son términos RDF tipados, nunca texto interpretado.

Dependencias: `argos-common`, rdflib 7.6 y PyYAML.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Fichero | `library/ontology/core/argos-core.ttl` | Ontología núcleo, versión `1.0.0` |
| Constantes | `ARGOS`, `NORMS`, `DPV`, `ELI`, `ODRL` | Espacios de nombres |
| Constantes | `CLASSES`, `OBJECT_PROPERTIES` (con dominio y rango), `DATATYPE_PROPERTIES`, `SEVERITIES`, `EVIDENCE_TYPES` | Vocabulario cerrado |
| Funciones | `bind_prefixes(graph)`, `load_core(path)` | Prefijos comunes y carga del núcleo |
| Fichero | `library/ontology/editorial/obligation-template.yaml` | Plantilla editorial comentada para el jurista |
| Funciones | `read_editorial(text)`, `to_internal(document)`, `to_editorial(document)` | Lectura estricta y traducción de claves |
| Funciones | `parse_obligation(document)`, `obligation_graph(spec)`, `compile_obligation(text)`, `compile_file(path)` | Validación y generación determinista de Turtle |
| Herramienta | `tools/ontology_compile.py [--check]` | Compila las plantillas o comprueba que el Turtle está al día |
| Tablas | `argos.ontology_bundles`, `argos.ontology_quads` (migración `0009`) | Versiones inmutables de la ontología |
| Funciones | `store_version(dsn, version, in_force_from, graph, sha256, manifest, signature)`, `version_in_force(dsn, at)`, `bundle_record(dsn, version)` | Carga y consulta de versiones |
| Clase | `OntologyStore(dsn, version=None, at=None)` con `sparql(query, bindings)` | SPARQL sobre una versión |
| Asiento | `ontology.load` | Carga de una versión en el diario |

## 5. Configuración

Sin configuración propia en este componente: el núcleo se carga desde `library/ontology/` del propio despliegue.

## 6. Seguridad y tratamiento de datos

- La ontología no contiene datos personales ni del cliente: solo normas, obligaciones y su relación con clases abstractas de activo.
- **Vocabulario cerrado:** el núcleo no puede declarar términos fuera de la lista (lo comprueba un test).
- **Idioma** (ADR-0005): identificadores y valores en inglés; etiquetas en castellano.
- **Decisiones aplicables:** ADR-0006 y nota de desviación ARG-031-033.

## 7. Operación

No aplica todavía: el núcleo es contenido estático. La carga versionada y la publicación firmada se documentan con sus componentes.

## 8. Verificación

- **`test_vocabulary.py`:** el núcleo OWL, su versión, las etiquetas en castellano, los dominios y rangos, la propiedad simétrica, la lista cerrada de tipos de evidencia y que no haya términos fuera del vocabulario.
- **`test_editorial_translation.py`:** ida y vuelta de la traducción, claves desconocidas y claves repetidas.
- **`test_store_pure.py` y `tests/integration/test_ontology_store.py`:** formato de versión y hash; carga, idempotencia y conflicto; vigencia por fecha independiente del orden de carga; SPARQL con parámetros tipados; inmutabilidad frente a `UPDATE`, `DELETE` y `TRUNCATE`; y asiento en el diario.
- **`test_editorial_compiler.py`:** validaciones de formato, severidad y fecha; grafo generado; bytes idénticos con el mismo YAML; literales con caracteres especiales sin inyección; y la plantilla que se entrega compila.

## 9. Limitaciones conocidas y pendientes

- **Componentes de la fase aún sin documentar:** se añaden con sus tareas.
- **Poblaciones normativas:** pendientes de validación jurídica.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-17 | Núcleo OWL de tres planos con tipo de evidencia y vocabulario cerrado | Fase 04 (ARG-031) |
| 0.1.0-alpha | 2026-09-17 | Plantilla editorial en castellano, capa de traducción y compilador determinista a Turtle | Fase 04 (ARG-038) |
| 0.1.0-alpha | 2026-09-17 | Almacén RDF versionado e inmutable en PostgreSQL con SPARQL por versión o fecha | Fase 04 (ARG-032) |
