# Interfaces que exporta la Fase 09 (estado real en main)

Generada a partir del código de `main` al cerrar la Fase 9 (tag `fase-09`). Los nombres de código están en inglés (ADR-0005).

- **Decisiones aplicables:**
  - ADR-0014 (seguridad de plataforma sin appliance);
  - la nota de desviación `docs/desviaciones/ARG-081-090.md` (aprobada);
  - las notas ARG-085, ARG-086, ARG-089 y ARG-081-082 (propuestas).

> **Probado en el entorno de desarrollo, no en el appliance.** Lo que necesita el equipo físico (imagen endurecida, Secure Boot, TPM y k3s) está escrito y probado sin hardware, y lo aplican F09-90, F09-91 y F09-92. El dossier distingue en cada medida lo que vale en cualquier despliegue de lo que solo se ha probado en el compose.

| Componente | Interfaz | Consumidores |
|---|---|---|
| ARG-081 | `platform/image/harden.sh` (idempotente; `ARGOS_HARDEN_ALLOW_SKIP=1` solo fuera de una construcción de imagen); `platform/image/audit/argos.rules`; `platform/image/hardening-exceptions.yaml`; `tools/cis_gate.py --report … [--exceptions] [--threshold 90]`; job `hardening-gate` del CI (reservado) | F09-90 (imagen real), auditoría CIS |
| ARG-082 | `platform/image/seal-disk.sh` (`ARGOS_DATA_DEVICE`); `platform/image/reseal-after-update.sh prepare\|confirm` | F09-91 (Secure Boot, TPM), el actualizador en el appliance |
| ARG-083 | `argos_tls` (`ReloadingTLS`, `issuer`); certificados de la PKI intermedia de Vault (`pki_int/issue/argos-svc`) por servicio; `argos_events` con `tls_from_environment()`; PostgreSQL solo `hostssl`; NATS con verificación de cliente; `platform/k8s/security/mtls.yaml` | Todos los servicios, F09-92 (cert-manager) |
| ARG-084 | Postura de contenedores del compose: usuario sin privilegios, `cap_drop: [ALL]`, `no-new-privileges` y raíz de solo lectura; `tests/security/test_compose_posture.py` y `tests/integration/test_container_posture.py` | F09-92 (Kyverno y AppArmor) |
| ARG-085 | Un rol de PostgreSQL por servicio (migración 0033); `argos_common.dynamic_db` (fichero de servicio de libpq rotado en caliente); motor `db/` de Vault con `vault_admin` (migración 0035, `platform/vault/database-engine.sh`); roles `svc-<servicio>` y `svc-backup` | Todos los servicios con base de datos, backup |
| ARG-086 | `argos_updater` (`verify_bundle`, `Updater.apply/recover`, `Step`, `ComposeOrchestrator`, `KubernetesOrchestrator`); CLI `argos-update verify\|apply\|recover\|watch`; `POST /api/v1/system/updates` (`system.update`, con segundo factor); `tools/release.py bundle` | Operación (Fase 10), esclusa |
| ARG-087 | `tools/sbom.py` (syft y grype fijados por digest); `tools/vuln_gate.py`; `platform/security/vex.yaml`; `make sbom`; SBOM e informes con su SHA-256 dentro del manifiesto de release; `verify_release_files` | Release, actualizador, dossier |
| ARG-088 | `argos_support` (`collect`, `build_package`, `open_package`, `DiagnosticsStore`, `Inspector`, `ComposeInspector`, `KubernetesInspector`); CLI `argos-support collect\|watch\|package`; `POST/GET /api/v1/support/diagnostics`, `POST …/{id}/package` (`support.diagnose`, `support.package` con segundo factor); `argos_connector.validators.scrub_identifiers` | Soporte, operador, esclusa |
| ARG-089 | `platform/backup/backup.py` y `restore_test.py` (restic fijado por digest); `make backup` y `make restore-test`; `argos.restore_tests` (migración 0037); métricas `argos_backup_last_restore_test_timestamp_seconds` y `…_success`; alertas `BackupRestoreTestStale` y `BackupRestoreTestFailed`; `platform/backup/systemd/` | Operación (Fase 10), alertas, dossier |
| ARG-090 | `argos_airgap` (`Gate.scan/export`, `EXPORT_KINDS`, `IMPORT_RULES`, `recorder`), importadores (`update_importer`, `content_importer`, `tsr_importer`) y exportadores (`tsq`, `dossier`, `credential`, `diagnostics`); `POST /api/v1/airgap/imports` y `/airgap/exports` (`airgap.import`, `airgap.export`, con segundo factor); migración 0038 | Appliance aislado, operador |
| Identidad | Segundo factor TOTP para `platform_admin` y `dpo_reviewer` (flujos del realm, `mfa_required`); `Identity.amr` e `Identity.sid`; `401` con `insufficient_user_authentication` (RFC 9470); sesiones cerradas en `argos.closed_sessions` (migración 0039); mismo origen para toda mutación | Consola, integraciones, F09-15 |
| Registro de seguridad | `argos_common.security_log` (`security.events` con su propia cadena, ráfagas plegadas, `verify_chain`); migración 0036; `/metrics` con `argos_security_events_total` y `argos_security_chain_ok`; reglas `deploy/dev/prometheus/rules/security.yml`; `GET /api/v1/security/events` | Operación, auditoría, dossier |
| Documentación | `docs/seguridad/`: modelo de amenazas, revisión de F1–F8 (SEC-001…060), batería de accesos (generada con `tools/security_report.py`), backup, endurecimiento y el dossier ENS/ISO (`docs/seguridad/dossier/`, empaquetado con `tools/docs_pack.py --security`) | Consultora, organismo, F09-97 |
| Pruebas | `tests/e2e/test_phase9_acceptance.py`; `tests/security/test_access_battery.py`; `tests/docs/test_security_dossier.py`; `tests/platform/`; `tests/integration/test_{updater,diagnostics,backup_restore,airgap,mtls,keycloak_mfa,security_log,service_roles,dynamic_credentials,closed_sessions}.py` | Fase 10, auditoría |
