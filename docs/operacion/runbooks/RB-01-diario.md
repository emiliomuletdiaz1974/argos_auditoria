---
id: RB-01
title: "El diario de auditoría no verifica"
alerts: [JournalNotIntact]
confidentiality: client
---
# RB-01 · El diario de auditoría no verifica

## Síntoma

La alerta `JournalNotIntact` (crítica) salta cuando el servicio de salud no consigue verificar la cadena del diario: un asiento no enlaza con el anterior, su hash no coincide con su contenido o falta una secuencia. En el panel de operación, el semáforo «Diario» está en rojo. La autoverificación de la release (`self-001`) también fallaría.

## Diagnóstico

1. Confirma que no es el propio servicio de salud el que falla: el panel «Servicios» en verde y la alerta `HealthServiceDown` sin disparar.
2. Pide los hechos al servicio de salud y mira qué verificación falló, la del tramo (`tail`) o la completa (`full`):

```bash
curl http://127.0.0.1:8009/facts
curl http://127.0.0.1:8009/metrics
```

3. Localiza el primer asiento anómalo con el verificador del diario, desde el anfitrión, y anota su secuencia. No cambies nada.

## Acción

- **No reinicies, no restaures y no borres nada.** Un diario que no verifica es una prueba: puede ser una manipulación.
- Congela el estado: haz una copia del volumen de la base (`make backup`), que conserva la cadena tal como está.
- Genera un paquete de diagnóstico para soporte (`argos-support collect`) y revísalo antes de enviarlo.
- Avisa al responsable de seguridad del organismo: es un incidente de integridad hasta que se demuestre lo contrario.

```bash
make backup
argos-support collect
```

## Verificación

- El incidente está abierto y registrado en el registro de seguridad del organismo.
- La copia congelada existe y su prueba de restauración reproduce la misma anomalía (misma secuencia).
- Nadie ha intentado «arreglar» el diario: la anomalía sigue donde estaba.

## Cuándo escalar

Siempre, y de inmediato: al responsable de seguridad del organismo y al soporte de ARGOS. Un diario roto invalida la evidencia de las campañas que lo anclan hasta que se investigue.
