---
id: MOD-argos-ontology
kind: module
title: Ontología normativa (argos-ontology)
module: argos-ontology
phases: ["04"]
version: 0.1.0-alpha
commit: a2f91e5
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

Implementa ARG-031 a ARG-040. Este documento cubre por ahora ARG-031 (núcleo), ARG-032 (almacén versionado), ARG-033 (aplicabilidad), ARG-034 (SHACL), ARG-035 (ODRL), ARG-037 (trazabilidad), ARG-040 (publicación firmada) y ARG-038 (flujo editorial y cinco puertas).

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

### Formas SHACL de coherencia (ARG-034)

Algunas obligaciones no sondean los sistemas del cliente, sino la coherencia de lo que ARGOS sabe de ellos. La parte relevante del grafo del inventario se exporta, con un mapeo fijo, a un grafo RDF efímero, y se valida en memoria con pySHACL (sin razonador ni red). Formas en `library/ontology/shapes/inventory-coherence.ttl`:

| Forma | Regla | Severidad | Mensaje para el DPD |
|---|---|---|---|
| `TreatmentShape` | Todo tratamiento declara base jurídica | Violación | Tratamiento sin base jurídica declarada |
| `TreatmentShape` | Todo tratamiento declara plazo de conservación | Aviso | Tratamiento sin plazo de conservación |
| `HealthDataSystemShape` | Todo sistema con columnas vivas de datos de salud figura en el registro de actividades | Violación | Sistema con datos de salud fuera del registro de actividades |
| `ConfirmedAISystemShape` | Todo sistema de IA confirmado tiene una única clase de riesgo del AI Act (`prohibited`, `high`, `limited`, `minimal`) | Violación | Sistema de IA confirmado sin clasificación de riesgo válida del AI Act |

Cada incumplimiento es un hallazgo `ShapeFinding(node, shape, message, severity)`, ordenado y determinista. Un valor vacío cuenta como ausente.

### Políticas ODRL de espacios de datos (ARG-035)

En los espacios de datos (Gaia-X, EHDS, Catena-X) las condiciones de uso viajan como políticas ODRL 2.2. ARGOS lee el **perfil acotado** que usan los espacios reales, no ODRL completo:
- **Restricciones:** `purpose`, `elapsedTime`, `dateTime` y `spatial`.
- **Deberes:** `delete` y `notify`.
- **Términos:** se aceptan con prefijo, como IRI completa o sin prefijo.

Cada regla verificable se traduce en una especificación de reto sobre el activo del espacio:

| Regla | Reto |
|---|---|
| Deber `delete` con plazo `PnYnMnD` | `ds-asset-retention` (`max_days`; con varios plazos, el más estricto) |
| Permiso con `purpose` | `ds-usage-purpose` (`allowed_purposes`) |
| Prohibición `distribute` o `share` | `ds-no-redistribution` |

**Lo que queda fuera del perfil no se ignora.** Entra aquí un operando o deber no soportado, una duración con horas o semanas, o un `delete` sin plazo. Cada caso queda en `Policy.unsupported` y genera al final un hallazgo `ds-unverifiable` (`finding_only: true`). Solo un documento ilegible (sin `uid`, sin `target` o con una regla sin `action`) lanza `PolicyError`.

### Reglas operativas OPA/Rego (ARG-036)

Las decisiones operativas que no son un umbral numérico simple viven como paquetes Rego en `library/policies/`. Cada paquete expone un objeto `verdict`:
- el evaluador de retos pasa la evidencia de la sonda como `input`;
- los parámetros aprobados del cliente se cargan en `data.client` desde `client/data.json` (en desarrollo, `deploy/dev/opa/client/data.json`, con datos sintéticos).

| Paquete | `input` | `data.client` | `verdict` |
|---|---|---|---|
| `argos.retention` | `category`, `treatment`, `max_age_days`, `out_of_term`, `documented_exceptions` | `retention_schedule[treatment].days` y, si el tratamiento no figura, `retention_defaults[category].days` | `compliant`, `applied_term_days`, `rule` |
| `argos.access` | `target`, `category`, `identities` (`name`, `profile`; sin perfil cuenta como no autorizado) | `authorized_profiles[category]` | `compliant`, `unauthorized` (ordenado), `total`, `rule` |

Reglas de decisión:
- **Conservación:** cumple si hay plazo aplicable y el registro más antiguo no lo supera. También cumple si todos los registros fuera de plazo tienen excepción documentada. Sin plazo aplicable, no cumple.
- **Accesos:** cumple si ninguna identidad queda fuera de los perfiles autorizados. Una categoría sin perfiles autorizados no autoriza a nadie.

El cliente Python `evaluate(package, input_doc, base_url)` llama a `POST /v1/data/<paquete>/verdict`. Valida antes el nombre del paquete (`ValueError`) y lanza `OpaError` si OPA no responde, contesta con error o el paquete no tiene `verdict` de tipo objeto.

### Resolutor de aplicabilidad (ARG-039)

El resolutor responde a la pregunta que arranca cada campaña: con la ontología vigente y el grafo de hoy, qué obligaciones aplican a qué activos y con qué retos se verifican. Cada ejecución sigue cuatro pasos:
1. **Obligaciones vigentes.** Con SPARQL sobre la versión cargada (`REQUIREMENTS`) obtiene las ternas obligación–clase de activo–reto, en orden estable.
   - Solo entran las obligaciones vigentes en la **fecha de la campaña** (hoy por defecto): `inForceFrom` incluida, `inForceUntil` excluida.
   - La fecha de carga de la ontología no cuenta; así, una norma que aplica en el futuro (por ejemplo, el EHDS) no entra hoy en los planes.
   - Las obligaciones sin reto quedan para la matriz de trazabilidad.
2. **Selectores.** Cada selector distinto se resuelve **una sola vez por ejecución** a través del protocolo `SelectorResolver`.
   - `StoreSelectorResolver` lo hace en proceso, con el mismo compilador, las mismas protecciones y las mismas páginas de `MAX_PAGE_SIZE` que la API del inventario.
   - Cuando haya token de servicio podrá resolverse por HTTP sin tocar el resolutor.
3. **Ámbito.** El único campo admitido es `system_ids`, una lista no vacía de textos que se normaliza ordenada y sin duplicados. El ámbito solo estrecha: las filas sin nodos dentro de él desaparecen.
   - Una clase sin selector (con su motivo de verificación pendiente, si lo tiene) o con un selector inválido va a `skipped` con su motivo; nunca se descarta en silencio.
4. **Persistencia, asiento y evento.**
   - La ejecución se guarda en `argos.applicability_runs` y, en la misma transacción, se anota `applicability.resolve` (actor `system:resolver`) en el diario.
   - Tras confirmar, si hay bus, publica `challenge.applicability_ready.v1`.

Cada fila del plan explica por sí sola por qué aplica: obligación, etiqueta, severidad, clase de activo, selector, reto y claves de nodo ordenadas.

### Biblioteca normativa v1

#### RGPD

> **Pendiente de validación jurídica.** Esta población está estructurada técnicamente, pero todavía no la ha validado el perfil jurídico. Cada plantilla lo indica en su primera línea, y no debe presentarse como validada hasta entonces.

Cubre el alcance aprobado para el v1: derechos de los interesados, registro de actividades, seguridad del tratamiento y brechas. También incluye los principios del artículo 5 que citan los retos. Hay 13 obligaciones técnicamente verificables:
- la norma y sus 12 artículos citados se declaran en `library/ontology/norms/RGPD.ttl`;
- las plantillas están en `library/ontology/editorial/OBL-RGPD-*.yaml`;
- el Turtle correspondiente se genera en `norms/generated/` con `tools/ontology_compile.py`.

Las obligaciones sobre datos personales en general aplican a las cinco clases de datos personales: `AC-stored-personal-data`, `-identifier-data`, `-contact-data`, `-financial-data` y `-special-category-data`.

| Bloque | Obligación | Artículo | Severidad | Reto |
|---|---|---|---|---|
| Principios | `OBL-RGPD-5-1` conservación limitada | 5.1.e | high | `ret-table-retention`, `ret-file-retention` (OPA `argos.retention`) |
| Principios | `OBL-RGPD-5-2` confidencialidad de categorías especiales | 5.1.f | high | `acc-special-category-profiles` (OPA `argos.access`) |
| Derechos | `OBL-RGPD-15-1` acceso en plazo | 15 | high | `dsr-access-request-term` |
| Derechos | `OBL-RGPD-17-1` supresión efectiva | 17 | high | `dsr-erasure-effective` |
| Registro de actividades | `OBL-RGPD-9-1` base jurídica de categorías especiales | 9.1 | critical | `coh-treatment-legal-basis` (SHACL) |
| Registro de actividades | `OBL-RGPD-30-1` sistemas declarados | 30.1 | high | `coh-ropa-declared-systems` (SHACL) |
| Registro de actividades | `OBL-RGPD-30-2` plazos declarados | 30.1.f | medium | `coh-treatment-retention-declared` (SHACL) |
| Registro de actividades | `OBL-RGPD-30-3` columnas sin clasificar | 30.1.c | medium | `coh-unclassified-columns` |
| Seguridad | `OBL-RGPD-32-1` cifrado en reposo de datos de salud | 32.1.a | critical | `sec-encryption-at-rest` |
| Seguridad | `OBL-RGPD-32-2` registro de accesos | 32.1.b | high | `sec-access-logging` |
| Seguridad | `OBL-RGPD-32-3` cifrado en tránsito | 32.1.b | high | `sec-encryption-in-transit` |
| Brechas | `OBL-RGPD-33-1` notificación en 72 h | 33.1 | critical | Pendiente de verificación: el simulacro necesita el motor de campañas |
| Brechas | `OBL-RGPD-33-2` registro documental | 33.5 | medium | `brc-breach-register` |

El catálogo provisional `library/challenges/catalog.yaml` contiene esos 13 retos, sin huérfanos; el motor de retos debe implementarlos con los mismos ids. La matriz de trazabilidad da 12 obligaciones cubiertas y 1 pendiente. No se declaran equivalencias con otros marcos: las aportará la matriz de solapamiento.

#### EHDS

> **Pendiente de validación jurídica**, igual que la población RGPD.

Reglamento (UE) 2025/327, ELI `http://data.europa.eu/eli/reg/2025/327/oj`. El alcance aprobado es el acceso primario y el uso secundario relevantes para un centro sanitario:
- la norma y sus artículos citados se declaran en `library/ontology/norms/EHDS.ttl`;
- las 7 plantillas están en `library/ontology/editorial/OBL-EHDS-*.yaml`;
- todas las obligaciones aplican a `AC-stored-health-data`.

**Fechas de aplicación (art. 105):**
- el reglamento está en vigor desde el 26-3-2025 (`inForceFrom` de la norma);
- cada obligación declara `vigente_desde: 2029-03-26`, fecha en que aplican los artículos 3 a 15 a las categorías prioritarias a), b) y c) y el capítulo IV;
- como el resolutor filtra por la fecha de la campaña, estas obligaciones no entran en los planes anteriores a esa fecha;
- la aplicación a las categorías d), e) y f) desde el 26-3-2031 queda para la validación jurídica.

| Uso | Obligación | Artículo | Severidad | Reto |
|---|---|---|---|---|
| Primario | `OBL-EHDS-3-1` acceso inmediato del paciente | 3 | high | `dsr-ehds-patient-access` |
| Primario | `OBL-EHDS-8-1` limitación del acceso decidida por el paciente | 8 | high | `dsr-ehds-access-restriction` |
| Primario | `OBL-EHDS-9-1` registro de accesos (quién, cuándo, qué; 3 años) | 9.2 | high | `sec-health-access-log-retention` |
| Primario | `OBL-EHDS-11-1` acceso profesional solo con relación asistencial | 11.1 | critical | `acc-care-relationship-access` |
| Primario | `OBL-EHDS-13-1` categorías prioritarias registradas en sistema HCE | 13.1 | medium | `coh-priority-categories-located` |
| Secundario | `OBL-EHDS-60-1` datos al organismo de acceso en 3 meses | 60.2 | medium | Pendiente de verificación: no hay organismo de acceso en el entorno del cliente |
| Secundario | `OBL-EHDS-60-2` descripción del conjunto de datos exacta y revisada al año | 60.3 | medium | `coh-dataset-description-current` |

Quedan fuera de esta población, a la espera de la validación jurídica:
- la rectificación (art. 6), la portabilidad (art. 7) y la autoexclusión (arts. 10 y 71);
- los requisitos de los sistemas HCE (capítulo III), que corresponden al fabricante;
- la seudonimización y el entorno de tratamiento seguro (arts. 66 y 73), que corresponden al organismo de acceso.

El catálogo provisional queda así en 19 retos.

Dependencias: `argos-common`, `argos-inventory`, rdflib 7.6, PyYAML, pySHACL 0.40 y httpx 0.28.

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
| Fichero | `library/ontology/shapes/inventory-coherence.ttl` | Formas SHACL de coherencia del inventario |
| Funciones | `export_graph(store)`, `load_shapes(shapes_dir)`, `validate_graph(data, shapes)`, `run_shapes(store, shapes=None)` | Exportación del grafo y validación SHACL |
| Funciones | `parse_policy(jsonld)`, `to_challenges(policy)`, `duration_days(iso)`; tipos `Policy`, `Rule`, `Constraint` y `PolicyError` | Lectura del perfil ODRL y traducción a retos |
| Ficheros | `library/policies/retention.rego`, `library/policies/access.rego` y sus `*_test.rego` | Paquetes `argos.retention` y `argos.access` |
| Función | `evaluate(package, input_doc, base_url="http://127.0.0.1:8181", *, client=None)` y `OpaError` | Veredicto de un paquete Rego |
| Contenedor | `opa` (`openpolicyagent/opa:1.20.2`, `127.0.0.1:8181`) | Servidor OPA de desarrollo con las políticas y `data.client` |
| Tabla | `argos.applicability_runs` (migración `0010`) | Ejecuciones inmutables: versión de ontología, `resolved_for`, ámbito, plan, omitidas, `pairs` y `nodes_total`; índice por `(campaign_id, created_at)` |
| Funciones | `resolve(dsn, ontology, selectors, scope, campaign_id=None, bus=None, at=None)`, `requirements(graph, at=None)`, `build_plan(requirements, selectors, scope)`, `check_scope(scope)`, `in_force(at, start, end)` | Resolución de aplicabilidad |
| Tipos | `ApplicabilityRun`, `Requirement`, `ResolvedNode`, protocolo `SelectorResolver` y `StoreSelectorResolver(store, page_size)` | Plan y resolución de selectores |
| Asiento | `applicability.resolve` (actor `system:resolver`) | Ejecución, versión de ontología, fecha, pares y nodos |
| Evento | `challenge.applicability_ready.v1` en `argos.challenge.applicability_ready` (stream `CHALLENGE`) | `run_id`, `campaign_id`, `ontology`, `pairs` |
| Herramienta | `tools/ontology_gates.py [--library DIR]` y `make ontology-gates` | Imprime `PASS`/`FAIL` por puerta; código 1 si alguna falla; paso del job `verify` del CI |

## 5. Configuración

- El núcleo se carga desde `library/ontology/` del propio despliegue.
- **Servidor OPA:** URL por parámetro `base_url` (por defecto `http://127.0.0.1:8181`); en los tests, variable `ARGOS_TEST_OPA`.
- **Parámetros del cliente para OPA:** `client/data.json` con `retention_schedule`, `retention_defaults` y `authorized_profiles`, aprobados en el despliegue.

## 6. Seguridad y tratamiento de datos

- La ontología no contiene datos personales ni del cliente: solo normas, obligaciones y su relación con clases abstractas de activo.
- **Vocabulario cerrado:** el núcleo no puede declarar términos fuera de la lista (lo comprueba un test).
- **Idioma** (ADR-0005): identificadores y valores en inglés; etiquetas en castellano.
- **Decisiones aplicables:** ADR-0006 y nota de desviación ARG-031-033.

## 7. Operación

- **Publicar una versión:** `uv run --env-file .env.example python tools/ontology_publish.py build --version X.Y.Z --in-force-from AAAA-MM-DD`, con un token de Vault con permiso de firma sobre `argos-content`.
- **Verificar un bundle recibido:** `tools/ontology_publish.py verify <bundle>`.
- **Cargar un bundle en el appliance:** `load_bundle`, que verifica antes de guardar.
- **Probar las políticas Rego:** `make policy-test` (ejecuta `opa test` en el contenedor; paso del job `verify` del CI).
- **Servidor OPA de desarrollo:** `docker compose -f deploy/dev/compose.yaml up -d --wait opa`. Tras cambiar políticas o datos se reinicia con `restart opa`: no se usa `--watch` porque los montajes de Windows no propagan eventos.

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
- **`test_shacl_pure.py` y `tests/integration/test_ontology_shacl.py`:**
  - inventario coherente sin hallazgos;
  - cada hueco con su forma, mensaje y severidad;
  - sobre el grafo real, tratamientos sin base jurídica ni plazo y sistema de salud sin declarar;
  - declaración completa sin hallazgos;
  - sistema de IA confirmado sin clase de riesgo.
- **`test_odrl_pure.py`:** perfil soportado sin prefijos, traducción a retos, cláusulas fuera del perfil convertidas en hallazgo (incluidas `PT12H`, `P1W` y `P`), documentos malformados rechazados y traducción determinista.
- **`library/policies/*_test.rego` (`make policy-test`):** 8 casos de conservación y accesos, incluidos el plazo por defecto, las excepciones documentadas y la identidad sin perfil.
- **`test_opa_pure.py` y `tests/integration/test_ontology_opa.py`:**
  - URL y cuerpo de la llamada;
  - nombres de paquete inválidos rechazados sin llamar;
  - errores HTTP, de red y veredictos ausentes o no objeto convertidos en `OpaError`;
  - con el servidor real, veredictos de conservación y accesos con `data.client`;
  - los paquetes de test no se cargan.
- **`test_resolver_pure.py` y `tests/integration/test_ontology_resolver.py`:**
  - ternas en orden estable y plan con su porqué;
  - cada selector resuelto una sola vez;
  - ámbito que solo estrecha, ámbitos inválidos rechazados y normalización;
  - selectores inválidos omitidos con su motivo;
  - vigencia con `inForceFrom` incluida e `inForceUntil` excluida;
  - sobre el grafo real, ejecución guardada, anotada y anunciada;
  - ámbito fuera del inventario con ejecución vacía;
  - páginas pequeñas con los mismos nodos;
  - obligaciones futuras fuera del plan;
  - ejecuciones inmutables.
- **`test_population_gdpr.py`:** plantillas con nombre igual a su id y dentro del alcance aprobado, todos los bloques poblados, artículos declarados como parte de la norma, retos presentes en el catálogo y solo la notificación de brechas pendiente de verificación.
- **`test_population_ehds.py`:** plantillas dentro del alcance, ambos usos poblados, fechas de aplicación del artículo 105 (no de la entrada en vigor), artículos declarados, retos en el catálogo y solo el plazo del organismo de acceso pendiente.
- **`test_editorial_compiler.py`:** validaciones de formato, severidad y fecha; grafo generado; bytes idénticos con el mismo YAML; literales con caracteres especiales sin inyección; y la plantilla que se entrega compila.

## 9. Limitaciones conocidas y pendientes

- **Componentes de la fase aún sin documentar:** se añaden con sus tareas.
- **Poblaciones normativas:** las poblaciones RGPD y EHDS están pendientes de validación jurídica; la población AI Act se añade con su tarea.

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
| 0.1.0-alpha | 2026-09-17 | Formas SHACL de coherencia del inventario validadas con pySHACL | Fase 04 (ARG-034) |
| 0.1.0-alpha | 2026-09-17 | Perfil ODRL de espacios de datos traducido a retos, con hallazgo de lo no verificable | Fase 04 (ARG-035) |
| 0.1.0-alpha | 2026-09-17 | Paquetes Rego de conservación y accesos, contenedor OPA y cliente `evaluate` | Fase 04 (ARG-036) |
| 0.1.0-alpha | 2026-09-17 | Resolutor de aplicabilidad por fecha de campaña con ejecuciones inmutables, asiento y evento | Fase 04 (ARG-039) |
| 0.1.0-alpha | 2026-09-17 | Población RGPD del v1: 13 obligaciones y 13 retos, pendiente de validación jurídica | Fase 04 (ARG-031) |
| 0.1.0-alpha | 2026-09-17 | Población EHDS del v1: 7 obligaciones aplicables desde 2029 y 6 retos, pendiente de validación jurídica | Fase 04 (ARG-031) |
