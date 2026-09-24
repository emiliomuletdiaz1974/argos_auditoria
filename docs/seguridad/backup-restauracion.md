# Backup cifrado con restauración probada

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Componente:** ARG-089 (F09-12) · **Confidencialidad:** `client`

**Una copia solo existe cuando su restauración se ha probado.** La fecha de la última prueba que pasó es una métrica, y una alerta avisa si caduca o si falla.

## Qué se copia

| Conjunto | Qué lleva | Cómo |
|---|---|---|
| `db` | Base de datos completa y roles sin contraseñas | `pg_dump -Fc` y `pg_dumpall --roles-only --no-role-passwords`. El usuario es efímero, del rol de solo lectura `svc_backup`: Vault lo crea para la ejecución y lo revoca al terminar |
| `evidence` | El almacén WORM de evidencia | Se lee en solo lectura |
| `config` | Secretos de Vault y estado del despliegue | En desarrollo, los secretos de `argos/`, el compose y el estado de sus servicios. En el appliance, `vault operator raft snapshot` y los manifiestos de k3s |

## Cómo se protege

- **Cifrado de extremo a extremo** con restic 0.18.1, en una imagen fijada por digest (ADR-0014).
- **La contraseña del repositorio** está en Vault (`argos/platform/backup`). Llega a restic en un fichero montado en solo lectura para cada orden y borrado al terminar. Nunca va en un argumento ni en una variable, así que no aparece en `docker inspect` ni en los registros.
- **Retención:** 14 copias diarias, 8 semanales y 12 mensuales, con `restic check` sobre un 5 % rotatorio de los datos en cada ejecución.
- **Destino:** en desarrollo, una carpeta local ignorada por git; en el appliance, el S3 o el SFTP del cliente.

## Cómo se prueba la restauración

1. Se restaura la última copia de `db` en una carpeta de trabajo.
2. Se levanta un PostgreSQL desechable de la misma imagen del entorno:
   - sin red (`--network none`) y sin puertos publicados, así que no puede conectarse a producción por error;
   - con una contraseña aleatoria en un fichero.
3. Se restauran los roles y el volcado.
4. Se verifica:
   - la cadena del diario, con el verificador del diario v1, y que su último asiento es el mismo en producción;
   - la cadena del registro de seguridad y sus columnas;
   - los recuentos de cada tabla y los nodos del grafo del inventario, frente a producción. Una tabla ausente o vacía en la copia es un fallo;
   - una muestra de objetos de evidencia de la copia, frente a la huella de `evidence_index`.
5. El resultado se guarda con su fecha:
   - una fila en `argos.restore_tests` (de solo inserción);
   - un asiento en el diario;
   - un evento en el registro de seguridad.
6. El contenedor y la carpeta se borran siempre, también si algo falla.

## Alertas

| Alerta | Cuándo | Severidad |
|---|---|---|
| `BackupRestoreTestStale` | Ninguna prueba ha pasado en 35 días (o no ha pasado nunca) | aviso |
| `BackupRestoreTestFailed` | La última prueba falló | crítica |

Las reglas están en `deploy/dev/prometheus/rules/backup.yml` y sus pruebas con `promtool` en `tests/backup/backup_rules_test.yml`.

## Cadencia

- **Backup:** diario a las 02:30.
- **Prueba:** mensual, el día 1 a las 04:00.

Son temporizadores de systemd en el nodo (`platform/backup/systemd/`), porque el backup necesita el orquestador y los volúmenes. En desarrollo se lanzan a mano con `make backup` y `make restore-test`.

## Medidas en desarrollo (2026-09-24)

Portátil de trabajo, base de 30 MB con 25 038 asientos de diario y 300 MB de evidencia.

| Operación | Tiempo |
|---|---|
| Backup de los tres conjuntos, con retención y comprobación | 26 s |
| Prueba de restauración completa | 11–12 s |

La restauración de producción que fija el RTO de 4 h se medirá en el hardware del appliance (Fase 10).

## Límites

- **Sin recuperación a un punto en el tiempo:** no hay archivado de WAL hasta la Fase 10 (nota de desviación ARG-089). El RPO es de 24 h, el del contrato.
- **El destino S3 o SFTP del cliente** está previsto en el código (`--repository s3:…`), pero sin probar: falta un destino real.
