---
id: RB-08
title: "Restauración completa desde copia"
procedure: true
confidentiality: client
---
# RB-08 · Restauración completa desde copia

## Síntoma

El appliance ha perdido su base de datos (disco dañado, borrado accidental, sustitución de hardware) y hay que devolverlo al estado de la última copia buena.

## Diagnóstico

1. Identifica la última copia cuya prueba de restauración pasó (`argos.restore_tests`, o el informe de la prueba mensual).
2. Asume la pérdida: todo lo ocurrido después de esa copia no estará.
3. Confirma que el almacén de evidencia está intacto. La evidencia sellada no está en la copia de la base: está en el WORM.

```bash
make restore-test
```

## Acción

1. Con los servicios de ARGOS parados, restaura la copia sobre una base vacía con el procedimiento de `docs/seguridad/backup-restauracion.md`.
2. Arranca los servicios y deja que el servicio de salud verifique el diario entero.
3. Lanza la autoverificación para tener evidencia de que el appliance restaurado está sano.

```bash
make selfcheck
```

## Verificación

- El diario y el registro de seguridad verifican enteros.
- La autoverificación termina sin hallazgos graves.
- Las campañas selladas antes de la copia siguen verificando con el comprobador público.

## Cuándo escalar

Si la restauración no verifica el diario, o si falta evidencia en el WORM de campañas que la base da por selladas: al soporte de ARGOS y al responsable de seguridad del organismo.
