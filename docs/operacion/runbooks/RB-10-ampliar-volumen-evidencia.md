---
id: RB-10
title: "Ampliar el volumen de evidencia"
procedure: true
confidentiality: client
---
# RB-10 · Ampliar el volumen de evidencia

## Síntoma

El volumen de evidencia se acerca a su límite (alerta `EvidenceDisk85`, RB-02) o la previsión de campañas lo llenará. La evidencia sellada no se puede borrar: la única salida es ampliar.

## Diagnóstico

1. Mira la ocupación y su tendencia en el panel de operación («Disco de evidencia»).
2. Calcula con la ficha de la talla (Especificación §5.6) cuánto espacio necesitan las campañas previstas de los próximos meses.
3. Comprueba con el responsable de infraestructura si el almacenamiento admite la ampliación en caliente.

## Acción

1. Haz una copia antes de tocar el almacenamiento:

```bash
make backup
```

2. Amplía el volumen con el procedimiento del fabricante del almacenamiento. Si no se puede en caliente, para antes el almacén de evidencia.
3. Arranca el almacén y espera a que el canario vuelva a 1.

## Verificación

- `argos_evidence_volume_used_ratio` baja en proporción a la ampliación.
- El canario WORM sigue en 1 y ninguna campaña ha quedado sin sellar.

## Cuándo escalar

Si el volumen no admite ampliación: al responsable de infraestructura y al comercial de ARGOS. Es un cambio de talla (Especificación §3.10).
