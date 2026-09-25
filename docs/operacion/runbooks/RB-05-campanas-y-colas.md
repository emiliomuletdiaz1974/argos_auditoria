---
id: RB-05
title: "Campañas paradas y colas que crecen"
alerts: [CampaignStuckAtGate, CircuitOpen, TsaQueueGrowing, ScanTooSlow]
confidentiality: client
---
# RB-05 · Campañas paradas y colas que crecen

## Síntoma

- `CampaignStuckAtGate`: una campaña lleva más de 60 horas esperando una aprobación. A las 72 horas la compuerta caduca y la campaña tiene que empezar de nuevo.
- `CircuitOpen`: el cortacircuitos de un sistema lleva 30 minutos abierto. El sistema responde lento y sus sondas esperan.
- `TsaQueueGrowing`: más de 50 peticiones de sello esperando y la cola sigue creciendo.
- `ScanTooSlow`: la última exploración de un sistema tardó más de 2 horas.

## Diagnóstico

1. En el panel de operación mira «Horas en compuerta sin aprobar», «Cortacircuitos abiertos», «Colas» y «Duración de la última exploración».
2. **Compuerta:** en la consola (Campañas), identifica la campaña y la compuerta, y quién debe aprobarla (DPO).
3. **Cortacircuitos:** pregunta al responsable del sistema si hay una incidencia o una carga anormal.
4. **Cola de sellado:** comprueba si la TSA responde. En modo aislado, la cola solo baja cuando se exportan las peticiones por la esclusa.

## Acción

- **Compuerta:** avisa al DPO. Si la campaña ya no tiene sentido, que la rechace, en vez de dejarla caducar.
- **Cortacircuitos:** no lo cierres a mano. Se cierra solo cuando el sistema vuelve a responder. Acuerda con su responsable una ventana más tranquila.
- **Cola de sellado:** en modo aislado, exporta las peticiones por la esclusa (RB-09) e importa las respuestas. Con red, revisa la conectividad con la TSA.
- **Exploración lenta:** revisa el presupuesto de carga del sistema y la talla del appliance.

## Verificación

- La compuerta queda aprobada o rechazada antes de las 72 horas.
- El cortacircuitos se cierra y las sondas del sistema avanzan.
- La cola de sellado baja en la siguiente ronda.

## Cuándo escalar

Una compuerta que nadie aprueba: al DPO y a su suplente. Un sistema que sigue lento tras la ventana acordada: al responsable del sistema. Una TSA que no responde con red: a quien la contrató.
