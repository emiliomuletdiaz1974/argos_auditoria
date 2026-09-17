---
id: MOD-argos-ontology
kind: module
title: Ontología normativa (argos-ontology)
module: argos-ontology
phases: ["04"]
version: 0.1.0-alpha
commit: 20b0e0e
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

Implementa ARG-031 a ARG-040. Este documento cubre por ahora ARG-031 (núcleo), ARG-032 (almacén versionado), ARG-033 (aplicabilidad), ARG-037 (trazabilidad), ARG-040 (publicación firmada) y ARG-038 (flujo editorial y cinco puertas).

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

### Publicación firmada (ARG-040)

La ontología viaja del equipo editorial a los appliances, incluidos los aislados, como un **bundle firmado**:
- **Contenido:** un tar.gz determinista con el Turtle de `ontology/`, las políticas `policies/**/*.rego` y el catálogo `challenges/`. Misma biblioteca, versión y fecha dan los mismos bytes.
- **Manifiesto** (`manifest.json`): versión, fecha de entrada en vigor y SHA-256 de cada fichero.
- **Firma:** el manifiesto se firma con la clave Ed25519 **`argos-content`** de Vault Transit. La clave no es exportable y es distinta de la de releases de software.

**Antes de cargar se verifica siempre** (`verify_bundle`, `load_bundle`), y el bundle se rechaza (`BundleRejectedError`) si:
- la firma no es válida o es de otra clave, incluida la de releases;
- el manifiesto no está en forma canónica o no describe un bundle de ontología;
- sobran, faltan o cambiaron ficheros respecto al manifiesto;
- el archivo no es un tar.gz válido, trae rutas inseguras o nombres repetidos, o supera los límites (5000 ficheros, 20 MB por fichero).

Solo un bundle verificado llega al almacén versionado.

### Plano de aplicabilidad (ARG-033)

La correspondencia entre clases abstractas («dato de salud almacenado») y nodos del inventario vive en la ontología, dentro del ciclo editorial, y no en código. Cada clase de activo lleva el **selector JSON** que resuelve la API del inventario y la etiqueta del grafo a la que apunta.

Clases base (`library/ontology/asset-classes/base.ttl`):

| Clase | Qué selecciona |
|---|---|
| `AC-stored-personal-data` | Columnas vivas clasificadas como dato personal |
| `AC-stored-identifier-data` | Columnas con identificadores oficiales |
| `AC-stored-contact-data` | Columnas con datos de contacto |
| `AC-stored-financial-data` | Columnas con datos financieros |
| `AC-stored-health-data` | Columnas con datos de salud |
| `AC-stored-special-category-data` | Columnas con cualquier categoría especial |
| `AC-unclassified-column` | Columnas vivas sin clasificar |
| `AC-pending-ai-system` | Sistemas de IA descubiertos pendientes de confirmar |
| `AC-missing-table` | Tablas desaparecidas del origen |
| `AC-cross-border-flow` | Pendiente de verificación: el grafo aún no registra el país de destino de los flujos |

Las clases basadas en clasificación exigen una confianza mínima de 0,5, que incluye las clasificaciones por diccionario (0,6) y las validadas. Una clase inválida se detecta con `asset_class_errors`:
- selector que no es JSON o que la API no acepta;
- etiqueta distinta de la del selector;
- ni selector ni motivo de verificación pendiente.

Para expresar «columna sin clasificar» y «sistema de IA pendiente», el selector de la API del inventario se amplió de forma compatible con dos campos, `unclassified` y `status` (nota de desviación ARG-031-033).

### Matriz de trazabilidad y catálogo de retos (ARG-037)

La promesa «cada reto trazado a la obligación que verifica» se comprueba también en sentido inverso, con una consulta reproducible sobre la ontología y el catálogo de retos:
- **Catálogo provisional** (`library/challenges/catalog.yaml`): identificadores de reto reservados, cada uno con su familia y el **tipo de evidencia** que producirá. Lo sustituye la biblioteca de retos de la Fase 05 conservando los identificadores.
- **Estados de cada obligación:** `covered` (tiene retos del catálogo), `pending` (declara un motivo de verificación pendiente) u `orphan`.
- **Errores que impiden publicar:**
  - obligación sin reto ni motivo pendiente, o con ambos;
  - reto referenciado que no está en el catálogo;
  - reto del catálogo que ninguna obligación usa.
- **Salidas:** `traceability.json` para la consola y `traceability.csv` (separado por `;`) como anexo contractual.

### Las cinco puertas editoriales (ARG-038)

Nada llega a una publicación sin pasar las cinco puertas del Plan Director. Se ejecutan en local (`make ontology-gates`) y en cada envío y pull request (job `verify` del CI):

| Puerta | Qué comprueba |
|---|---|
| **Sintaxis** | Cada plantilla compila; el Turtle generado está al día, sin plantillas sin generar ni generados sin plantilla; todo el Turtle de `ontology/` se parsea |
| **Consistencia** | Dominios y rangos de las propiedades del núcleo; solo términos `argos:` del vocabulario cerrado; severidades válidas; clases de activo con selector válido para la API del inventario |
| **Cobertura** | Toda obligación tiene reto o motivo pendiente (no ambos) y aplica al menos a una clase de activo |
| **Trazabilidad** | Toda obligación cita su artículo, y ese artículo es parte de una norma declarada (`library/ontology/norms/<NORMA>.ttl`); todo reto referenciado está en el catálogo; no hay retos huérfanos |
| **Firma** | El bundle se construye dos veces con los mismos bytes, se firma con una clave Ed25519 efímera, se verifica y su grafo se carga en seco, sin necesitar Vault |

Si la sintaxis falla, las demás puertas se marcan como omitidas en lugar de ejecutarse sobre un grafo roto. Cada puerta tiene en los tests un caso que pasa y al menos un error plantado que la hace fallar.

Dependencias: `argos-common`, `argos-inventory`, rdflib 7.6 y PyYAML.

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
| Funciones | `build_bundle(library_dir, version, in_force_from)`, `sign_bundle(manifest, signer)`, `verify_bundle(bundle, signature, public_key)`, `bundle_graph(verified)`, `load_bundle(dsn, bundle, signature, public_key)` | Construcción, firma, verificación y carga |
| Herramienta | `tools/ontology_publish.py build --version X.Y.Z --in-force-from AAAA-MM-DD [--output DIR]` | Escribe `argos-ontology-X.Y.Z.tar.gz`, su firma `.sig` y la clave pública `content.pub` |
| Herramienta | `tools/ontology_publish.py verify <bundle> [--public-key FICHERO]` | Verifica un bundle sin cargarlo |
| Clave | Vault Transit `argos-content` (Ed25519) | Firma de contenidos normativos |
| Fichero | `library/ontology/asset-classes/base.ttl` | Clases de activo base con sus selectores |
| Funciones | `load_asset_classes(path)`, `asset_classes(graph)`, `compiled_selector(asset_class)`, `asset_class_errors(graph)` | Lectura, compilación y validación de clases de activo |
| Fichero | `library/challenges/catalog.yaml` | Catálogo provisional de retos (id, familia, tipo de evidencia, descripción) |
| Funciones | `load_challenge_catalog(path)`, `library_graph(library_dir)`, `build_matrix(graph, catalog)`, `matrix_json(rows)`, `matrix_csv(rows)` | Matriz de trazabilidad y sus errores |
| Herramienta | `tools/ontology_traceability.py [--library DIR] [--output DIR]` | Escribe la matriz en JSON y CSV; termina con código 1 si hay errores |
| Funciones | `gate_syntax`, `gate_consistency`, `gate_coverage`, `gate_traceability`, `gate_signature`, `run_gates(library_dir)` y `GateResult(name, ok, errors)` | Las cinco puertas |
| Herramienta | `tools/ontology_gates.py [--library DIR]` y `make ontology-gates` | Imprime `PASS`/`FAIL` por puerta; código 1 si alguna falla; paso del job `verify` del CI |

## 5. Configuración

Sin configuración propia en este componente: el núcleo se carga desde `library/ontology/` del propio despliegue.

## 6. Seguridad y tratamiento de datos

- La ontología no contiene datos personales ni del cliente: solo normas, obligaciones y su relación con clases abstractas de activo.
- **Vocabulario cerrado:** el núcleo no puede declarar términos fuera de la lista (lo comprueba un test).
- **Idioma** (ADR-0005): identificadores y valores en inglés; etiquetas en castellano.
- **Decisiones aplicables:** ADR-0006 y nota de desviación ARG-031-033.

## 7. Operación

- **Publicar una versión:** `uv run --env-file .env.example python tools/ontology_publish.py build --version X.Y.Z --in-force-from AAAA-MM-DD`, con un token de Vault con permiso de firma sobre `argos-content`.
- **Verificar un bundle recibido:** `tools/ontology_publish.py verify <bundle>`.
- **Cargar un bundle en el appliance:** `load_bundle`, que verifica antes de guardar.

## 8. Verificación

- **`test_vocabulary.py`:** el núcleo OWL, su versión, las etiquetas en castellano, los dominios y rangos, la propiedad simétrica, la lista cerrada de tipos de evidencia y que no haya términos fuera del vocabulario.
- **`test_editorial_translation.py`:** ida y vuelta de la traducción, claves desconocidas y claves repetidas.
- **`test_store_pure.py` y `tests/integration/test_ontology_store.py`:** formato de versión y hash; carga, idempotencia y conflicto; vigencia por fecha independiente del orden de carga; SPARQL con parámetros tipados; inmutabilidad frente a `UPDATE`, `DELETE` y `TRUNCATE`; y asiento en el diario.
- **`test_bundle_pure.py` y `tests/integration/test_ontology_bundle.py`:**
  - bytes idénticos con la misma biblioteca;
  - rechazo de bundles manipulados, de un manifiesto reescrito con hashes coherentes, de otra clave y de datos que no son un bundle;
  - clave `argos-content` Ed25519 no exportable;
  - carga de un bundle firmado en Vault;
  - rechazo de un bundle firmado con la clave de releases.
- **`test_applicability_pure.py` y `tests/integration/test_ontology_asset_classes.py`:**
  - clases base documentadas y sanas, con errores plantados detectados;
  - sobre el grafo real, cada clase se ejecuta en AGE;
  - los datos de salud coinciden con la verdad terreno;
  - clasificadas y sin clasificar parten las columnas vivas;
  - el sistema de IA pendiente aparece.
- **`test_traceability_pure.py`:**
  - estados `covered`, `pending` y `orphan`;
  - cada error de publicación;
  - validación del catálogo (ids, tipos de evidencia y duplicados);
  - salidas deterministas en JSON y CSV.
- **`test_gates_pure.py`:** una biblioteca sana pasa las cinco puertas, la biblioteca que se entrega también, y cada puerta rechaza su error plantado; incluye la herramienta y su código de salida.
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
| 0.1.0-alpha | 2026-09-17 | Bundle determinista firmado con `argos-content` y verificación antes de cargar | Fase 04 (ARG-040) |
| 0.1.0-alpha | 2026-09-17 | Plano de aplicabilidad con clases de activo base y selectores validados | Fase 04 (ARG-033) |
| 0.1.0-alpha | 2026-09-17 | Matriz de trazabilidad obligación–reto y catálogo provisional de retos | Fase 04 (ARG-037) |
| 0.1.0-alpha | 2026-09-17 | Cinco puertas editoriales con errores plantados y paso de CI | Fase 04 (ARG-038) |
