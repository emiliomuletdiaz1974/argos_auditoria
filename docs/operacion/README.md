# Libro de operación de ARGOS

Los runbooks del appliance (ARG-099). Cada alerta de `platform/observability/objectives.yaml` enlaza con el suyo, y la consola lo muestra junto a la alerta activa. Todos siguen el mismo orden: síntoma, diagnóstico, acción, verificación y cuándo escalar.

| Runbook | Responde a |
|---|---|
| [RB-01 · El diario de auditoría no verifica](runbooks/RB-01-diario.md) | `JournalNotIntact` |
| [RB-02 · El almacén de evidencia no guarda o se llena](runbooks/RB-02-almacen-evidencia.md) | `WormWriteFailing`, `EvidenceDisk85` |
| [RB-03 · Copias sin hacer o sin probar](runbooks/RB-03-copias.md) | `BackupRestoreTestFailed`, `BackupRestoreTestStale`, `BackupStale` |
| [RB-04 · El registro de seguridad avisa](runbooks/RB-04-seguridad.md) | `SecurityChainBroken`, `SecuritySignatureRejected`, `SecurityRefusalBurst` |
| [RB-05 · Campañas paradas y colas que crecen](runbooks/RB-05-campanas-y-colas.md) | `CampaignStuckAtGate`, `CircuitOpen`, `TsaQueueGrowing`, `ScanTooSlow` |
| [RB-06 · La plataforma: certificados y servicio de salud](runbooks/RB-06-plataforma.md) | `CertificatesExpiring`, `HealthServiceDown` |
| [RB-07 · Conmutación al nodo de reserva (talla M)](runbooks/RB-07-conmutacion-talla-m.md) | Procedimiento |
| [RB-08 · Restauración completa desde copia](runbooks/RB-08-restauracion-completa.md) | Procedimiento |
| [RB-09 · Operación de la esclusa de soportes](runbooks/RB-09-esclusa.md) | Procedimiento |
| [RB-10 · Ampliar el volumen de evidencia](runbooks/RB-10-ampliar-volumen-evidencia.md) | Procedimiento |
| [RB-11 · Renovar los certificados externos](runbooks/RB-11-certificados-externos.md) | Procedimiento |
| [RB-12 · Simulacro trimestral](runbooks/RB-12-simulacro-trimestral.md) | Procedimiento (`tools/drill.py`) |

Las pruebas de `tests/docs/test_runbooks.py` comprueban que ninguna alerta se queda sin runbook, que cada runbook tiene las cinco secciones y que cada orden que pide ejecutar existe en el repositorio.

Los comandos de los runbooks usan el entorno de desarrollo (`docker compose -f deploy/dev/compose.yaml …`). En el appliance, las mismas acciones se hacen sobre k3s; esa adaptación llega con el hardware (F10-90).

La alta disponibilidad de cada talla está en [alta-disponibilidad.md](alta-disponibilidad.md).

La prueba del banco k3s con datos sintéticos (K-99) está en [banco-k3s.md](banco-k3s.md). Cómo se despliega, paso a paso: [guia-despliegue-banco.md](guia-despliegue-banco.md).
