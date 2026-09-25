---
id: RB-02
title: "El almacén de evidencia no guarda o se llena"
alerts: [WormWriteFailing, EvidenceDisk85]
confidentiality: client
---
# RB-02 · El almacén de evidencia no guarda o se llena

## Síntoma

- `WormWriteFailing` (crítica): el canario del servicio de salud no pudo escribir y releer un objeto en el almacén WORM dos veces seguidas. No se puede sellar evidencia.
- `EvidenceDisk85` (crítica): el volumen de evidencia supera el 85 %. La evidencia sellada no se puede borrar, así que el volumen solo crece.

## Diagnóstico

1. Mira los semáforos «Almacén WORM» y «Disco de evidencia» del panel de operación.
2. Comprueba que el almacén responde y cuánto ocupa:

```bash
curl http://127.0.0.1:8009/facts
docker compose -f deploy/dev/compose.yaml ps evidence-store
```

3. Si el canario falla con el disco lleno, la causa es el espacio. Si falla con espacio libre, mira el log del almacén (`docker compose logs evidence-store`).

## Acción

- **Almacén caído:** reinícialo y espera a que el canario vuelva a 1. Las campañas en sellado reintentan solas.
- **Disco lleno o casi lleno:** amplía el volumen siguiendo RB-10. No borres objetos: el almacén está en modo conformidad y no lo permitiría.
- Mientras tanto, no lances campañas nuevas.

```bash
docker compose -f deploy/dev/compose.yaml restart evidence-store
```

## Verificación

- `argos_worm_healthy` vuelve a 1 durante al menos 5 minutos.
- La ocupación baja del 85 % después de ampliar el volumen.
- Las campañas que esperaban el sello terminan selladas.

## Cuándo escalar

Si el canario sigue fallando con espacio libre y el almacén en marcha: al soporte de ARGOS, con un paquete de diagnóstico. Si no hay espacio para ampliar: al responsable de infraestructura del organismo (RB-10).
