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
3. Decide con el responsable del organismo si se conmuta o se espera. El script de conmutación de F10-09 (`platform/ha/size-m/failover.sh`) hace estas comprobaciones en su modo de simulacro.

## Acción

1. Ejecuta el script de conmutación en modo simulacro y lee su informe.
2. Si el informe lo permite, ejecútalo con confirmación: promueve la réplica, verifica el diario en el promovido y lo deja en el diario (`ha.failover`).
3. Redirige el acceso de los usuarios al nuevo principal.
4. Cuando el antiguo principal vuelva, reincorpóralo como réplica con el script de reincorporación. Nunca lo arranques como principal.

## Verificación

- El diario verifica en el nuevo principal.
- La consola y las campañas funcionan contra él.
- Hay un asiento `ha.failover` con la decisión y el retraso asumido.

## Cuándo escalar

Si el simulacro no permite la conmutación, o si el diario no verifica tras promover: al soporte de ARGOS antes de seguir.
