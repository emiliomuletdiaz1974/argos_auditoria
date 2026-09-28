# Alta disponibilidad por tallas

ARG-095 · ADR-0015, punto 8. La disponibilidad se compra por talla, y cada talla promete solo lo que cumple.

| Talla | Qué hay | Conmutación |
|---|---|---|
| S | Un nodo, RAID, copia probada | Restauración desde copia (RB-08) |
| M | Dos nodos: el segundo es réplica física de PostgreSQL, con slot | **Asistida**: la decide una persona (RB-07) |
| L | Tres nodos con quórum (etcd de k3s y Patroni), replicación síncrona | Automática |

## Talla M: por qué la conmutación no es automática

Dos principales escribiendo evidencia a la vez serían dos verdades. En un almacén de evidencia eso es peor que diez minutos de parada con una persona decidiendo. Los scripts:

- `platform/ha/size-m/failover.py`:
  - sin `--confirm` es un simulacro y no cambia nada;
  - se niega si el principal responde, también cuando responde con un error (una contraseña, una base que no existe): solo un principal inalcanzable está caído;
  - enseña el retraso de la réplica y avisa si supera el máximo; si nunca reprodujo nada, lo dice como desconocido;
  - para si `pg_promote` no confirma la promoción;
  - promueve, verifica el diario en el promovido antes de nada más y deja `ha.failover` en el diario.
- `platform/ha/size-m/rejoin.py`:
  - sin `--confirm` es un simulacro y no vacía nada;
  - devuelve el antiguo principal como réplica del nuevo;
  - se niega si sigue corriendo como principal;
  - lo vacía y lo clona del nuevo principal con su propio slot;
  - deja `ha.rejoin` en el diario.

En desarrollo, la pareja es el perfil `ha` del compose (`ha-node-a` y `ha-node-b`). No es la base del entorno: sirve para probar la conmutación sin parar nada más. `tests/integration/test_ha_size_m.py` recorre RB-07 entero: simulacro, rechazo con el principal vivo, promoción con el diario íntegro y reincorporación.

## Talla L

`platform/ha/size-l/patroni.yaml` configura Patroni:
- consenso en el etcd de k3s, en los tres nodos y con TLS;
- replicación síncrona estricta;
- TLS con contraseña en toda conexión por red;
- API REST con certificado de cliente.

Está validada en estático (`tests/platform/test_ha_size_l.py`) y se aplica con tres nodos reales en F10-92.
