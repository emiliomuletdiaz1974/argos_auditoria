---
id: FASE-NN
kind: phase
title: Fase NN · <nombre de la fase>
phase: "NN"
version: <versión de la plataforma al cerrar la fase>
commit: <hash corto del commit etiquetado fase-NN>
date: <AAAA-MM-DD del cierre>
status: current
confidentiality: client
---

# Fase NN · <nombre de la fase>

## 1. Resumen

Qué capacidad aporta la fase a ARGOS, en un párrafo legible por el cliente.

## 2. Alcance

- Componentes ARG incluidos.
- Lo que quedó fuera de la fase y dónde se aborda.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| | `modulos/<nombre>.md` | |

## 4. Prueba de la fase

- Criterio de aceptación del Plan Director.
- Cómo se ejecutó (entorno, datos sintéticos, test `tests/e2e/test_phaseNN_acceptance.py`).
- Resultado y fecha.

## 5. Decisiones y desviaciones

ADR y notas de desviación aprobadas que afectan a la fase, con un resumen de cada una.

## 6. Interfaces que exporta

Enlace a `docs/fases/interfaces-FNN.md` y resumen de lo que consumen las fases siguientes.

## 7. Pendientes al cierre

Lo que queda abierto sin bloquear (medidas, validaciones, acciones manuales) y su responsable.

## 8. Identificación del cierre

Tag `fase-NN`, commit y fecha.
