---
id: RB-03
title: "Copias sin hacer o sin probar"
alerts: [BackupRestoreTestFailed, BackupRestoreTestStale, BackupStale]
confidentiality: client
---
# RB-03 · Copias sin hacer o sin probar

## Síntoma

- `BackupStale`: no hay copia completada en las últimas 26 horas. El punto de recuperación ya es más viejo que un día.
- `BackupRestoreTestStale`: ninguna prueba de restauración ha pasado en 35 días.
- `BackupRestoreTestFailed` (crítica): la última prueba de restauración falló. Hasta que una pase, las copias se tratan como inservibles.

## Diagnóstico

1. Mira el semáforo «Copias» y el panel «Horas desde el último éxito de cada trabajo».
2. Lee el motivo del último fallo en `argos.restore_tests` (columna `reasons`).
3. Comprueba que el destino de las copias tiene espacio y que el temporizador de copia está activo en el nodo.

## Acción

- Haz una copia y pruébala a mano:

```bash
make backup
make restore-test
```

- Si la prueba falla por la copia (corrupta o incompleta), haz una nueva y vuelve a probar.
- Si falla por el entorno de prueba (disco, imagen), corrígelo: la copia puede estar bien.

## Verificación

- Hay una fila nueva en `argos.restore_tests` con `result = 'passed'`.
- `argos_backup_last_restore_test_success` vuelve a 1 y las alertas se resuelven solas.

## Cuándo escalar

Si dos pruebas seguidas fallan con copias nuevas: al soporte de ARGOS, con el motivo de `argos.restore_tests` y un paquete de diagnóstico.
