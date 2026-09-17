---
id: FASE-05
kind: phase
title: Fase 05 · Motor de retos
phase: "05"
version: 0.1.0-alpha
commit: df46b33
date: 2026-09-17
status: current
confidentiality: client
---

# Fase 05 · Motor de retos

> **Contenido normativo pendiente de validación jurídica.** El motor está terminado y probado de extremo a extremo. Los retos verifican obligaciones de las poblaciones v1, que están estructuradas técnicamente pero **no validadas por un perfil jurídico** y no deben presentarse como validadas. Esa revisión se hace en F04-98, y lo que cambie allí cambia qué mide un reto, no cómo funciona el motor.

## 1. Resumen

La Fase 05 es donde ARGOS deja de describir y empieza a **comprobar**. Una campaña toma la instantánea del inventario y la ontología vigentes, las fija, y de ahí saca una lista de unidades de trabajo inertes: un reto, un nodo concreto del cliente y la sonda ya resuelta. El DPD puede leer el plan exactamente como se va a ejecutar, antes de que se ejecute.

Cada unidad produce un **veredicto** con una de cuatro respuestas —cumple, no cumple, no demostrado o no concluyente— que nace siempre en la misma función determinista, nunca en un modelo de lenguaje. Los incumplimientos se convierten en hallazgos con su ciclo de vida, y la campaña termina con un **sello** que permite comprobar después que ningún veredicto se tocó.

## 2. Alcance

- **Incluido:** ARG-041 a ARG-050 — lenguaje de retos y biblioteca, compilador sobre la instantánea, muestreo estadístico, evaluador determinista, workflow de campaña con compuertas humanas, sondas con minimización, ciclo de vida de hallazgos, API de campañas, reejecución de subsanación y sello.
- **Incluido por decisión de F05-00:** el sujeto sintético (ADR-0008), con el que se comprueban los derechos del interesado sin tocar datos de personas reales.
- **Fuera:** la IA local que asiste al editor de retos (Fase 06), la evidencia firmada y la credencial verificable (Fase 07) y la consola (Fase 08).

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| argos-challenge-engine | `modulos/argos-challenge-engine.md` | 0.1.0-alpha |
| argos-ontology (ampliado) | `modulos/argos-ontology.md` | 0.1.0-alpha |
| argos-sql (ampliado) | `modulos/argos-sql.md` | 0.1.0-alpha |

## 4. Prueba de la fase

Criterio del Plan Director §8.2: una campaña completa contra el entorno de demostración, con al menos quince retos de dos normas, compuertas aprobadas por una persona, veredictos idénticos a la verdad terreno, reejecución determinista, sello verificable y subsanación.

Se ejecutó con `make dev` (fuentes simuladas PostgreSQL y MariaDB, Temporal, OPA, Vault) sobre datos exclusivamente sintéticos, en `tests/e2e/test_phase5_acceptance.py`, con una base de datos propia por ejecución. La verdad terreno (`tests/fixtures/campaign_ground_truth.yaml`) se escribió a mano en F05-01, **antes** de que existiera el motor, y la prueba la carga y la compara sin ajustarla.

Resultado, 2026-09-17: los seis criterios en verde.

1. **Campaña completa:** 17 retos de RGPD y AI Act sobre los dos sistemas, con el sujeto sintético inyectado por el script del cliente y su supresión ejercida solo en el sistema clínico.
2. **Compuertas:** la campaña espera en `awaiting:start` hasta que una persona aprueba; la aprobación queda con su nombre en el diario. El doble control de la compuerta de muestreo se comprueba aparte, porque ningún reto de la biblioteca que se entrega usa sonda de muestreo.
3. **Veredictos y hallazgos:** coinciden exactamente con la verdad terreno, incluidos los seis incumplimientos plantados, y el agregado por sistema es el previsto.
4. **Reejecución:** una segunda campaña sobre la misma instantánea da el mismo contenido de veredicto para cada reto y nodo. El identificador de unidad lleva la campaña, así que se compara la evidencia, no el identificador.
5. **Sello:** `verify_seal` da verdadero; al alterar un veredicto, falso.
6. **Subsanación:** el cliente corrige uno de los plantados y `RemediationRun` lo cierra con el mismo reto que lo encontró; el que no se corrigió se reabre, sin contar una ocurrencia nueva.

## 5. Decisiones y desviaciones

- **ADR-0007 · Motor de retos.** El reto es un documento declarativo, no código; el veredicto nace en una función pura con cuatro valores posibles; la campaña se fija a una instantánea y a una versión de la ontología.
- **ADR-0008 · Sujeto sintético.** ARGOS genera y registra los sujetos; el cliente los inyecta y ejerce los derechos. La plataforma conserva su lectura de solo lectura: nunca escribe en un sistema del cliente.
- **Notas de desviación** `ARG-041-042`, `ARG-043-047`, `ARG-045-046` y `ARG-048-050`, aprobadas en F05-00.
- **Decisión del usuario (F05-00):** claves del DSL en inglés con capa de traducción al castellano, cuatro valores de veredicto y sello de campaña dentro de esta fase.

## 6. Interfaces que exporta

`docs/fases/interfaces-F05.md`. Lo que consumen las fases siguientes: la Fase 06 conecta la IA local al editor de retos sin tocar el evaluador; la Fase 07 construye la evidencia y la credencial sobre el veredicto y el sello; la Fase 08 lee campañas, plan, veredictos y hallazgos por la API.

## 7. Pendientes al cierre

- **Cuatro obligaciones sin fuente de evidencia en la demostración** (`brc-breach-register`, `coh-ai-training-data-governance`, `sec-ai-event-logging`, `sec-ai-log-retention`): sus ids siguen reservados en el catálogo y la campaña los reporta como no verificables con su motivo. Se escriben cuando exista de dónde leerlos.
- **La columna de referencia de la retención va escrita en cada variante** del reto: el nombre de una columna no puede viajar como parámetro.
- **`acc-special-category-profiles` deja fuera las cuentas de superusuario**, que necesitan su propio reto o una declaración del cliente.
- **Validación jurídica** de las poblaciones y de la verdad terreno de aplicabilidad (F04-13, F04-15, F04-17, F04-19 y F04-98).
- La lista completa está en `ARGOS-pendientes.md`.

## 8. Identificación del cierre

Tag `fase-05`, commit `df46b33`, 2026-09-17.
