---
id: MOD-argos-ontology
kind: module
title: Ontología normativa (argos-ontology)
module: argos-ontology
phases: ["04"]
version: 0.1.0-alpha
commit: 081aa48
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

Implementa ARG-031 a ARG-040. Este documento cubre por ahora ARG-031, el núcleo de la ontología.

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

Dependencias: `argos-common` y rdflib 7.6.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Fichero | `library/ontology/core/argos-core.ttl` | Ontología núcleo, versión `1.0.0` |
| Constantes | `ARGOS`, `NORMS`, `DPV`, `ELI`, `ODRL` | Espacios de nombres |
| Constantes | `CLASSES`, `OBJECT_PROPERTIES` (con dominio y rango), `DATATYPE_PROPERTIES`, `SEVERITIES`, `EVIDENCE_TYPES` | Vocabulario cerrado |
| Funciones | `bind_prefixes(graph)`, `load_core(path)` | Prefijos comunes y carga del núcleo |

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

`services/ontology/tests/test_vocabulary.py` comprueba el núcleo OWL, la versión, las etiquetas en castellano, los dominios y rangos, la propiedad simétrica, la lista cerrada de tipos de evidencia y que no haya términos fuera del vocabulario.

## 9. Limitaciones conocidas y pendientes

- **Componentes de la fase aún sin documentar:** se añaden con sus tareas.
- **Poblaciones normativas:** pendientes de validación jurídica.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-17 | Núcleo OWL de tres planos con tipo de evidencia y vocabulario cerrado | Fase 04 (ARG-031) |
