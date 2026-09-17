---
id: MOD-argos-challenge-engine
kind: module
title: Motor de retos y campañas (argos-challenge-engine)
module: argos-challenge-engine
phases: ["01"]
version: 0.1.0-alpha
commit: 1aadd28
date: 2026-09-17
status: draft
confidentiality: client
---

# Motor de retos y campañas (argos-challenge-engine)

## 1. Propósito

Servicio que orquestará las campañas de verificación (retos, sondas, criterios y evidencias) sobre Temporal. En su estado actual contiene la **base** que se construyó en la Fase 01 (ARG-007): el worker, la política de reintentos y el patrón de workflows y actividades que usará el motor completo de la Fase 05 (ARG-041…050).

## 2. Alcance y límites

- **Hoy:** un worker de Temporal con un workflow de humo (`SmokeCampaign`) que ejecuta una sonda simulada y anota el resultado en el diario de auditoría.
- **No incluye todavía:** biblioteca de retos, compilación de selectores, campañas reales ni sellado de evidencia. Este documento está en estado `draft` y se completa en la Fase 05.

## 3. Arquitectura

- **Workflows** (`workflows.py`): deterministas y **sin entrada/salida**, para que Temporal pueda reejecutarlos desde su historial.
- **Actividades** (`activities.py`): toda la entrada/salida (sondas y escritura en el diario) vive aquí, con reintentos y límite de tiempo.
- **Worker** (`worker.py`): registra workflows y actividades en la cola `argos-campaigns`.

Dependencias: `argos-common` (configuración, registro y diario) y el SDK de Temporal.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Constante | `TASK_QUEUE = "argos-campaigns"` | Cola de tareas del dominio de campañas |
| Función | `create_worker(client, task_queue)` | Construye el worker con workflows y actividades registrados |
| Constante | `RETRY_POLICY` | 3 intentos, retroceso ×2 desde 200 ms |
| Workflow | `SmokeCampaign` | Workflow de humo del patrón |
| Actividades | `smoke_probe(system)`, `record_in_journal(action, payload)` | Sonda simulada y asiento en el diario |
| Proceso | `python -m argos_challenges.worker` | Arranque del worker |

## 5. Configuración

`ARGOS_TEMPORAL_ADDRESS` y `ARGOS_DATABASE_URL` (para el diario), desde `argos-common`.

## 6. Seguridad y tratamiento de datos

- Cada actividad que produce un resultado relevante lo anota en el diario de auditoría encadenado.
- El workflow de humo no accede a sistemas del cliente.

## 7. Operación

- Temporal en desarrollo en `127.0.0.1:7233`.
- El worker se arranca con `uv run python -m argos_challenges.worker`; aún no tiene contenedor propio en el entorno de desarrollo (ver §9).

## 8. Verificación

`tests/integration/test_temporal.py`: ejecución del workflow de humo, reintentos de actividades y asiento en el diario contra Temporal real.

## 9. Limitaciones conocidas y pendientes

- El motor de retos completo se construye en la Fase 05.
- El worker no tiene contenedor en `deploy/dev/compose.yaml` (pendiente para la Fase 05).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Worker de Temporal con workflow de humo, reintentos y asientos en el diario | Fase 01 (ARG-007) |
