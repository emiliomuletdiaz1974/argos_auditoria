---
id: FASE-03
kind: phase
title: Fase 03 · Inventario y grafo de conocimiento
phase: "03"
version: 0.1.0-alpha
commit: 5df4822
date: 2026-09-16
status: current
confidentiality: client
---

# Fase 03 · Inventario y grafo de conocimiento

## 1. Resumen

La Fase 03 convierte lo que leen los conectores en un **inventario vivo y verificable**:
- qué sistemas existen y qué datos guardan;
- de qué categoría es cada dato;
- cómo fluyen los datos entre sistemas;
- qué sistemas de IA hay;
- qué cambió desde la última exploración.

Las instantáneas inmutables permiten repetir cualquier verificación sobre el mismo estado del inventario.

## 2. Alcance

- **Componentes incluidos:** ARG-021 a ARG-030.
- **Fuera de la fase:**
  - el modelo de clasificación asistida (hay interfaz y cola de revisión; el modelo llega en la Fase 06);
  - los detectores basados en registros;
  - la medición en el hardware del appliance.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| Inventario y grafo | [`modulos/argos-inventory.md`](../modulos/argos-inventory.md) | 0.1.0-alpha |
| Validadores de identificadores (en el SDK) | [`modulos/argos-connector-sdk.md`](../modulos/argos-connector-sdk.md) | 0.1.0-alpha |

Además:
- las migraciones `0003` a `0008`;
- la verdad terreno del inventario de demostración;
- el informe legible del inventario;
- el banco de capacidad reproducible.

## 4. Prueba de la fase

**Criterio del Plan Director:**
- un escaneo completo del entorno de demostración coincide con la verdad terreno mantenida a mano;
- tras cambios provocados, un segundo escaneo produce exactamente esos cambios;
- una instantánea previa sigue íntegra y consultable mientras el grafo cambia.

**Ejecución (2026-09-16):** test `tests/e2e/test_phase3_acceptance.py` en base de datos propia, con datos sintéticos.

**Resultado: aprobada a la primera.**
- Sistemas, tablas, clasificaciones, flujos y candidatos de IA idénticos a la verdad terreno.
- Deltas exactamente los esperados, ni uno más.
- Instantánea íntegra y servida igual por la API GraphQL.
- Diario íntegro.
- Suite completa en verde (779 tests) y cobertura total del 96,43 %.

**Rendimiento** (tras el cierre, decisión del cliente de optimizar antes de la Fase 04):
- se eliminaron las consultas con coste lineal en el tamaño del grafo;
- extrapolado a 50 000 tablas, en el equipo de desarrollo: 1,17 h el inventario completo y 1,02 h la reexploración diaria, frente a los objetivos de 24 h y 2 h;
- selector de la API en 62 ms de mediana.

## 5. Decisiones y desviaciones

- **Nota ARG-021-023:** reglas comprobadas de Apache AGE 1.5.0 e ingesta idempotente con procedencia.
- **Nota ARG-024-025:** validación de identificadores en origen y cola de revisión humana.
- **Nota ARG-026-028:** catálogo y tratamientos, flujos por catálogo del motor y por estructura, e IA confirmada solo por una persona.
- **Nota ARG-029-030:** API GraphQL de solo lectura con selector cerrado, y planificador con Temporal.

## 6. Interfaces que exporta

Tabla completa, reglas de AGE y resultados del banco de capacidad en `docs/fases/interfaces-F03.md`. Consumen el inventario:
- la Fase 04 (aplicabilidad normativa por categoría de dato);
- la Fase 05 (campañas contra instantáneas);
- la Fase 07 (evidencia);
- la Fase 08 (consola).

## 7. Pendientes al cierre

- **Capacidad** en el hardware real del appliance.
- **Remuestreo de contenidos** con IA local (Fase 06).
- **Detectores basados en registros.**
- **Reactivar** el Schedule de reexploración en el despliegue.

## 8. Identificación del cierre

Tag `fase-03`, commit `5df4822`, 2026-09-16. Mejora de rendimiento posterior en los commits `2058cec` y `ef65519`.
