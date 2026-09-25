---
id: RB-12
title: "Simulacro trimestral del libro de operación"
procedure: true
confidentiality: client
---
# RB-12 · Simulacro trimestral del libro de operación

## Síntoma

Cada trimestre, el técnico del organismo ensaya dos runbooks sacados a sorteo, para que el día de la incidencia no sea la primera vez. Un paso que no se puede hacer tal como está escrito es una corrección del runbook, no un fallo de la persona.

## Diagnóstico

1. Elige una ventana en la que el appliance no tenga campañas en compuerta.
2. Avisa al DPO de que habrá un simulacro: algunos pasos se ensayan, no se ejecutan.

## Acción

Lanza el simulacro con tu nombre de usuario. La herramienta sortea dos runbooks, te lleva sección a sección, lo cronometra y lo deja en el diario:

```bash
uv run python tools/drill.py --operator <tu-usuario>
```

En cada paso pulsa Intro si se puede hacer tal como está escrito, o contesta «no» si no se puede.

## Verificación

- Hay un asiento `ops.drill` en el diario con los runbooks, los segundos y el resultado.
- Cada paso marcado con «no» tiene su corrección del runbook, hecha o anotada.

## Cuándo escalar

Si un runbook no se puede seguir en ningún paso: al soporte de ARGOS, para reescribirlo antes del siguiente trimestre.
