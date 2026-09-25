---
id: RB-07
title: "Conmutación al nodo de reserva (talla M)"
procedure: true
confidentiality: client
---
# RB-07 · Conmutación al nodo de reserva (talla M)

## Síntoma

El nodo principal de una talla M no responde y no va a volver pronto (avería de hardware, corte prolongado). La talla M tiene un segundo nodo en espera con replicación asíncrona. La conmutación es asistida: la decide una persona, nunca el sistema solo.

## Diagnóstico

1. Confirma que el principal está caído de verdad y no solo aislado de la red. Un principal vivo y otro promovido serían dos verdades, y en un almacén de evidencia eso es peor que la parada.
2. Mira el retraso de la réplica: lo que no llegó a replicarse se pierde.
3. Decide con el responsable del organismo si se conmuta o se espera. El script de conmutación (`platform/ha/size-m/failover.py`) hace estas comprobaciones en su modo de simulacro.

## Acción

1. Ejecuta el script en modo simulacro. Comprueba que el principal no responde, que la réplica es una réplica y cuánto retraso lleva; no cambia nada:

```bash
uv run python platform/ha/size-m/failover.py --primary-dsn <principal> --replica-dsn <réplica>
```

2. Si el informe lo permite y el responsable lo decide, ejecútalo con confirmación. Promueve la réplica, verifica el diario en el promovido y deja `ha.failover` en el diario. Si el principal responde, se niega:

```bash
uv run python platform/ha/size-m/failover.py --primary-dsn <principal> --replica-dsn <réplica> --confirm
```

3. Redirige el acceso de los usuarios al nuevo principal.
4. Cuando el antiguo principal vuelva, reincorpóralo como réplica: se vacía y se clona del nuevo principal, y queda `ha.rejoin` en el diario. Nunca lo arranques como principal.

```bash
uv run python platform/ha/size-m/rejoin.py --node <antiguo> --node-dsn <antiguo> --primary <nuevo> --primary-dsn <nuevo> --compose-file deploy/dev/compose.yaml
```

## Verificación

- El diario verifica en el nuevo principal.
- La consola y las campañas funcionan contra él.
- Hay un asiento `ha.failover` con la decisión y el retraso asumido.

## Cuándo escalar

Si el simulacro no permite la conmutación, o si el diario no verifica tras promover: al soporte de ARGOS antes de seguir.
