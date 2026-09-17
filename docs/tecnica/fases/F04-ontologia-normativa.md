---
id: FASE-04
kind: phase
title: Fase 04 · Ontología normativa
phase: "04"
version: 0.1.0-alpha
commit: f65bdf6
date: 2026-09-17
status: current
confidentiality: client
---

# Fase 04 · Ontología normativa

> **Cierre técnico.** La plataforma de la fase está terminada y probada de extremo a extremo. El **contenido normativo** (obligaciones RGPD, EHDS y AI Act, y la verdad terreno de aplicabilidad) está estructurado técnicamente pero **pendiente de validación jurídica**, y no debe presentarse como validado. El cierre jurídico se identificará con el tag `fase-04`.

## 1. Resumen

La Fase 04 convierte la normativa en **datos verificables**. Para cada obligación, ARGOS sabe:
- de qué artículo deriva y desde cuándo es exigible;
- a qué activos del inventario aplica;
- con qué retos se verifica y qué evidencia producen.

Con eso, al empezar una campaña, ARGOS responde a qué obligaciones aplican a qué sistemas y datos del cliente, y por qué. Guarda la respuesta de forma inmutable.

El contenido normativo viaja en paquetes firmados que el appliance verifica antes de cargar. Lo mantiene un proceso editorial con cinco puertas automáticas y un compromiso interno de 30 días desde la publicación oficial de una norma.

## 2. Alcance

- **Componentes incluidos:** ARG-031 a ARG-040.
  - Núcleo OWL de tres planos (normativo, aplicabilidad y verificación), almacén versionado, plano de aplicabilidad y formas SHACL.
  - Políticas ODRL de espacios de datos y reglas OPA/Rego.
  - Matriz de trazabilidad, flujo editorial con cinco puertas, resolutor de aplicabilidad y publicación firmada.
- **Biblioteca v1:** 28 obligaciones (13 RGPD, 7 EHDS y 8 AI Act) y 27 retos en el catálogo provisional.
- **Ajustes de clasificación (decisión del cliente, 2026-09-17):**
  - referencias a pacientes como dato personal;
  - puntuaciones de tablas clínicas como dato de salud;
  - categorías especiales distintas de la salud;
  - revisión de un DPO sintético en la demostración;
  - cifrado en reposo sobre todas las categorías especiales.
- **Fuera de la fase:**
  - la **validación jurídica** del contenido, a la espera de un perfil jurídico-técnico;
  - la **implementación de los retos**, que corresponde al motor de retos de la Fase 05;
  - las equivalencias con ENS y NIS2, que propondrá la validación jurídica.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| Ontología normativa | [`modulos/argos-ontology.md`](../modulos/argos-ontology.md) | 0.1.0-alpha |
| Inventario y grafo (selector y clasificación ampliados) | [`modulos/argos-inventory.md`](../modulos/argos-inventory.md) | 0.1.0-alpha |

Además:
- las migraciones `0009` (almacén de la ontología) y `0010` (ejecuciones de aplicabilidad);
- la biblioteca `library/` (núcleo, clases de activo, formas SHACL, políticas Rego, plantillas editoriales y catálogo de retos);
- el proceso editorial (`docs/ontologia/proceso-editorial.md`);
- las herramientas de compilación, puertas, trazabilidad, solapamiento y publicación;
- la verdad terreno de aplicabilidad sobre la instantánea de demostración.

## 4. Prueba de la fase

**Criterio del Plan Director:**
- el paquete v1 pasa las cinco puertas editoriales;
- el bundle es reproducible, se firma, se verifica y se carga, y un bundle alterado tras la firma se rechaza antes de cargarse;
- la aplicabilidad sobre la instantánea de demostración coincide exactamente con la verdad terreno;
- un error editorial plantado lo rechaza su puerta;
- los motores SHACL, OPA y ODRL responden sobre la misma instantánea.

**Ejecución (2026-09-17):** test `tests/e2e/test_phase4_acceptance.py` contra el entorno de desarrollo, en una base de datos propia que se borra al terminar, con datos sintéticos. La firma se hace con la clave `argos-content` de Vault y OPA se ejecuta en su contenedor.

**Resultado: 3 de 3 pruebas superadas.**
- Cinco puertas en verde; el error plantado lo rechaza la puerta de trazabilidad.
- Bundle con bytes idénticos en dos construcciones, firmado y cargado; el alterado se rechaza y el almacén queda vacío.
- Plan de aplicabilidad idéntico a la verdad terreno en las dos fechas de campaña: 49 filas a 16-9-2026 y 55 a 26-3-2029, cuando empieza a aplicar el EHDS.
- Hallazgos SHACL, veredicto OPA de conservación y traducción ODRL los esperados.
- Suite completa en verde (1058 tests), con una cobertura total del 96,54 %.

**Advertencia:** la verdad terreno contra la que se compara es **provisional**. Refleja lo que dice la biblioteca sin validar, no lo que exige la ley.

## 5. Decisiones y desviaciones

- **ADR-0006:** pila de la ontología (rdflib, pySHACL, OPA y almacén RDF en PostgreSQL) y plantilla editorial en castellano con capa de traducción.
- **Nota ARG-031-033:** tres planos, almacén versionado inmutable y aplicabilidad mediante el selector de la API del inventario.
- **Nota ARG-034-040:** perfil ODRL acotado, reglas OPA solo para decisiones no numéricas, cinco puertas, resolutor con ejecuciones inmutables y bundle firmado con clave propia de contenidos.
- **Decisiones del cliente del 2026-09-17:**
  - verdad terreno provisional sin validación jurídica;
  - ajustes de clasificación y de la demostración;
  - cierre técnico sin validación jurídica (opción A), para no detener la Fase 05.

## 6. Interfaces que exporta

Tabla completa, reglas comprobadas y cifras de la biblioteca en `docs/fases/interfaces-F04.md`. Consumen la ontología:
- la **Fase 05**, que implementa los 27 retos con los mismos ids y lanza campañas a partir del plan de aplicabilidad;
- la **Fase 07**, que asocia la evidencia a la obligación y al artículo;
- la **Fase 08**, que muestra el plan, la matriz de trazabilidad y el solapamiento en la consola;
- la **Fase 10**, que actualiza los contenidos con bundles firmados.

## 7. Pendientes al cierre

- **Validación jurídica** de las poblaciones RGPD, EHDS y AI Act y de la verdad terreno de aplicabilidad. Responsable: perfil jurídico-técnico, por asignar. Al terminar se crea el tag `fase-04`.
- **Decisiones para esa validación:**
  - qué columnas técnicas pueden considerarse sin datos personales;
  - la clase de riesgo del sistema de IA de la demostración y si el selector debe filtrar por clase de riesgo;
  - la aplicación del EHDS a las categorías d) a f) desde 2031;
  - las equivalencias con ENS y NIS2.
- **Implementación de los 27 retos** del catálogo provisional (Fase 05).
- **Verificación pendiente** de la notificación de brechas en 72 h y del plazo del organismo de acceso del EHDS.

## 8. Identificación del cierre

Tag `fase-04-tecnica`, 2026-09-17. El commit del cierre es el que lleva ese tag; el contenido de la biblioteca corresponde a `f65bdf6`.
