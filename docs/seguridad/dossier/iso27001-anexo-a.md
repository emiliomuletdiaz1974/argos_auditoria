# Controles del Anexo A de la ISO/IEC 27001:2022

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Dossier de seguridad v1** · **Confidencialidad:** `client`

Una fila por control del Anexo A. Los títulos siguen la versión española de la norma, abreviados. La columna *ENS* da la medida del Real Decreto 311/2022 que cubre lo mismo, cuando la hay. La [tabla del ENS](ens-medidas.md) tiene el detalle, y los estados se explican en el [índice del dossier](README.md).

## 5 · Controles organizativos

| Control | Nombre | ENS | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|---|
| 5.1 | Políticas de seguridad de la información | org.1, org.2 | responsabilidad del organismo | — | — |
| 5.2 | Roles y responsabilidades | org.1 | responsabilidad del organismo | — | Los roles del producto están en `services/api/argos_api/authz/permissions.yaml` |
| 5.3 | Segregación de funciones | op.acc.3 | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/integration/test_separation_of_duties.py` | — |
| 5.4 | Responsabilidades de la dirección | org.1 | responsabilidad del organismo | — | — |
| 5.5 | Contacto con las autoridades | op.exp.7 | responsabilidad del organismo | — | — |
| 5.6 | Contacto con grupos de interés especial | op.exp.7 | responsabilidad del organismo | — | — |
| 5.7 | Inteligencia de amenazas | op.pl.1 | implementada | `docs/seguridad/modelo-amenazas.md`, `tools/vuln_gate.py` | Base de datos de vulnerabilidades actualizada en cada release |
| 5.8 | Seguridad de la información en la gestión de proyectos | op.pl.2 | implementada | `docs/adr/0014-seguridad-de-plataforma.md`, `docs/decisiones/README.md` | Cada fase con su revisión de seguridad |
| 5.9 | Inventario de información y otros activos asociados | op.exp.1 | implementada | `tools/sbom.py`, `docs/seguridad/modelo-amenazas.md` | Activos del producto y SBOM; el inventario del organismo es suyo |
| 5.10 | Uso aceptable de la información y otros activos | org.2 | responsabilidad del organismo | — | — |
| 5.11 | Devolución de activos | mp.per.2 | responsabilidad del organismo | — | — |
| 5.12 | Clasificación de la información | mp.info.2 | responsabilidad del organismo | — | Los documentos del producto se marcan `client` o `internal`: `tools/docs_pack.py` |
| 5.13 | Etiquetado de la información | mp.info.2, mp.si.1 | responsabilidad del organismo | — | — |
| 5.14 | Transferencia de información | mp.si.4, mp.com.2 | implementada en desarrollo | `services/airgap/argos_airgap/__init__.py`, `tests/integration/test_airgap.py`, `libs/tls/argos_tls/__init__.py` | — |
| 5.15 | Control de acceso | op.acc.2 | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/contract/test_api_authz.py` | — |
| 5.16 | Gestión de identidades | op.acc.1 | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `tests/integration/test_keycloak.py` | — |
| 5.17 | Información de autenticación | op.acc.5, op.acc.6 | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `tests/integration/test_keycloak_mfa.py` | Contraseñas con hash en el realm; TOTP para los roles que deciden |
| 5.18 | Derechos de acceso | op.acc.4 | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `services/api/argos_api/authz/permissions.yaml` | — |
| 5.19 | Seguridad de la información en las relaciones con proveedores | op.ext.1 | responsabilidad del organismo | — | — |
| 5.20 | Seguridad en los acuerdos con proveedores | op.ext.1 | responsabilidad del organismo | — | — |
| 5.21 | Seguridad en la cadena de suministro TIC | op.ext.3 | implementada | `tools/sbom.py`, `tools/vuln_gate.py`, `libs/common/argos_common/release.py` | — |
| 5.22 | Seguimiento, revisión y cambios de los servicios de proveedores | op.ext.2 | responsabilidad del organismo | — | — |
| 5.23 | Seguridad en el uso de servicios en la nube | op.nub.1 | responsabilidad del organismo | — | El producto no usa servicios en la nube |
| 5.24 | Planificación y preparación de la gestión de incidentes | op.exp.7 | responsabilidad del organismo | — | — |
| 5.25 | Evaluación y decisión sobre eventos de seguridad | op.exp.7, op.mon.3 | implementada en desarrollo | `deploy/dev/prometheus/rules/security.yml`, `tests/integration/test_security_log.py` | Las alertas las decide el producto; la respuesta, el organismo |
| 5.26 | Respuesta a incidentes | op.exp.7 | responsabilidad del organismo | — | El producto aporta el paquete de diagnóstico: `services/support/argos_support/__init__.py` |
| 5.27 | Aprendizaje de los incidentes | op.exp.9 | responsabilidad del organismo | — | — |
| 5.28 | Recopilación de evidencias | op.exp.8 | implementada | `libs/common/argos_common/journal.py`, `libs/common/argos_common/security_log.py`, `tests/integration/test_journal_pg.py` | Diario y registro encadenados, verificables fuera de ARGOS |
| 5.29 | Seguridad durante una interrupción | op.cont.2 | responsabilidad del organismo | — | — |
| 5.30 | Preparación de las TIC para la continuidad del negocio | op.cont.3, mp.info.6 | implementada en desarrollo | `platform/backup/restore_test.py`, `tests/integration/test_backup_restore.py` | — |
| 5.31 | Requisitos legales, reglamentarios y contractuales | org.1 | responsabilidad del organismo | — | — |
| 5.32 | Derechos de propiedad intelectual | org.2 | responsabilidad del organismo | — | Licencias de las dependencias en el SBOM: `tools/sbom.py` |
| 5.33 | Protección de los registros | op.exp.8, mp.info.6 | implementada | `libs/common/argos_common/journal.py`, `services/evidence/argos_evidence/worm.py`, `tests/integration/test_worm_conformance.py` | Registros encadenados y evidencia en almacén WORM |
| 5.34 | Privacidad y protección de datos personales | mp.info.1 | implementada | `connectors/sdk/argos_connector/minimize.py`, `connectors/sdk/tests/test_sdk_minimize.py` | — |
| 5.35 | Revisión independiente de la seguridad | op.pl.1 | responsabilidad del organismo | — | La revisión interna del producto está en `docs/seguridad/revision-f01-f08.md` |
| 5.36 | Cumplimiento de políticas, reglas y normas de seguridad | org.2 | responsabilidad del organismo | — | — |
| 5.37 | Procedimientos operativos documentados | org.3 | implementada | `docs/tecnica/README.md`, `tools/docs_pack.py` | Cada módulo documenta su operación, y el paquete se genera para el organismo |

## 6 · Controles de personas

| Control | Nombre | ENS | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|---|
| 6.1 | Comprobación de antecedentes | mp.per.1 | responsabilidad del organismo | — | — |
| 6.2 | Términos y condiciones del empleo | mp.per.2 | responsabilidad del organismo | — | — |
| 6.3 | Concienciación, educación y formación | mp.per.3, mp.per.4 | responsabilidad del organismo | — | — |
| 6.4 | Proceso disciplinario | mp.per.2 | responsabilidad del organismo | — | — |
| 6.5 | Responsabilidades tras el cese o cambio de empleo | mp.per.2 | responsabilidad del organismo | — | — |
| 6.6 | Acuerdos de confidencialidad | mp.per.2 | responsabilidad del organismo | — | — |
| 6.7 | Trabajo en remoto | mp.eq.3 | responsabilidad del organismo | — | El soporte no tiene acceso remoto: `services/support/argos_support/__init__.py` |
| 6.8 | Notificación de eventos de seguridad | op.exp.7 | responsabilidad del organismo | — | — |

## 7 · Controles físicos

| Control | Nombre | ENS | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|---|
| 7.1 | Perímetros de seguridad física | mp.if.1 | responsabilidad del organismo | — | — |
| 7.2 | Entrada física | mp.if.1, mp.if.2 | responsabilidad del organismo | — | — |
| 7.3 | Seguridad de oficinas, despachos e instalaciones | mp.if.1 | responsabilidad del organismo | — | — |
| 7.4 | Supervisión de la seguridad física | mp.if.1 | responsabilidad del organismo | — | — |
| 7.5 | Protección contra amenazas físicas y ambientales | mp.if.5, mp.if.6 | responsabilidad del organismo | — | — |
| 7.6 | Trabajo en áreas seguras | mp.if.1 | responsabilidad del organismo | — | — |
| 7.7 | Puesto de trabajo despejado y pantalla limpia | mp.eq.1, mp.eq.2 | responsabilidad del organismo | — | — |
| 7.8 | Emplazamiento y protección de los equipos | mp.if.3 | responsabilidad del organismo | — | — |
| 7.9 | Seguridad de los activos fuera de las instalaciones | mp.eq.3 | responsabilidad del organismo | — | — |
| 7.10 | Soportes de almacenamiento | mp.si.1, mp.si.4 | implementada en desarrollo | `services/airgap/argos_airgap/__init__.py`, `tests/integration/test_airgap.py` | La esclusa gestiona el uso del soporte; su custodia es del organismo |
| 7.11 | Servicios de suministro | mp.if.4 | responsabilidad del organismo | — | — |
| 7.12 | Seguridad del cableado | mp.if.1 | responsabilidad del organismo | — | — |
| 7.13 | Mantenimiento de los equipos | op.exp.4 | pendiente de hardware | `services/updater/argos_updater/__init__.py` | Mantenimiento del appliance: F09-91 (arranque medido y resellado tras actualizar) |
| 7.14 | Eliminación o reutilización segura de equipos | mp.si.5 | pendiente de hardware | `platform/image/seal-disk.sh` | Un disco sellado al TPM es ilegible fuera del equipo: F09-91 |

## 8 · Controles tecnológicos

| Control | Nombre | ENS | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|---|
| 8.1 | Dispositivos finales de usuario | mp.eq.3 | responsabilidad del organismo | — | — |
| 8.2 | Derechos de acceso privilegiado | op.acc.4 | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/security/test_access_battery.py`, `services/api/migrations/0033_service_roles.sql` | Segundo factor para administrar; un rol de base de datos por servicio |
| 8.3 | Restricción del acceso a la información | op.acc.2 | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/contract/test_api_authz.py` | — |
| 8.4 | Acceso al código fuente | mp.sw.1 | responsabilidad del organismo | — | Repositorio del fabricante; el organismo recibe releases firmadas |
| 8.5 | Autenticación segura | op.acc.5, op.acc.6 | implementada en desarrollo | `tests/integration/test_keycloak_mfa.py`, `services/api/argos_api/sessions.py`, `tests/security/test_access_battery.py` | — |
| 8.6 | Gestión de capacidades | op.pl.4 | implementada en desarrollo | `tests/integration/test_inventory_benchmark.py`, `connectors/sdk/argos_connector/budget.py` | — |
| 8.7 | Protección contra el malware | op.exp.6 | pendiente de hardware | `libs/common/argos_common/release.py` | F09-90 (sistema operativo) y F09-92 (firma de imágenes en k3s) |
| 8.8 | Gestión de las vulnerabilidades técnicas | op.exp.4 | implementada | `tools/vuln_gate.py`, `platform/security/vex.yaml`, `tests/tools/test_vuln_gate.py` | — |
| 8.9 | Gestión de la configuración | op.exp.2, op.exp.3 | pendiente de hardware | `platform/image/harden.sh`, `tools/cis_gate.py` | F09-90 |
| 8.10 | Eliminación de la información | mp.si.5 | implementada en desarrollo | `platform/backup/backup_common.py`, `services/airgap/argos_airgap/__init__.py` | Retención de copias y zonas de trabajo que se vacían; el borrado del soporte es del organismo |
| 8.11 | Enmascaramiento de datos | mp.info.1 | implementada | `connectors/sdk/argos_connector/minimize.py`, `services/support/argos_support/scrub.py` | — |
| 8.12 | Prevención de fugas de datos | mp.info.1, mp.si.4 | implementada | `services/airgap/argos_airgap/__init__.py`, `services/airgap/tests/test_gate_pure.py` | Solo sale lo de una lista cerrada, depurado |
| 8.13 | Copias de seguridad de la información | mp.info.6 | implementada en desarrollo | `platform/backup/backup.py`, `tests/integration/test_backup_restore.py` | — |
| 8.14 | Redundancia de las instalaciones de tratamiento | op.cont.4 | responsabilidad del organismo | — | — |
| 8.15 | Registro de eventos | op.exp.8 | implementada | `libs/common/argos_common/security_log.py`, `tests/integration/test_security_log.py` | — |
| 8.16 | Actividades de supervisión | op.mon.2, op.mon.3 | implementada en desarrollo | `deploy/dev/prometheus/rules/security.yml`, `services/api/argos_api/security_events.py` | — |
| 8.17 | Sincronización del reloj | op.exp.8 | pendiente de hardware | `platform/image/audit/argos.rules` | La hora del appliance (y la auditoría de sus cambios) es de F09-90 |
| 8.18 | Uso de programas de utilidad privilegiados | op.acc.4 | pendiente de hardware | `platform/image/audit/argos.rules` | auditd registra toda ejecución como root: F09-90 |
| 8.19 | Instalación de software en sistemas en producción | op.exp.5 | implementada en desarrollo | `services/updater/argos_updater/__init__.py`, `tests/integration/test_updater.py` | Solo software firmado, por el actualizador |
| 8.20 | Seguridad de las redes | mp.com.1 | pendiente de hardware | `platform/k8s/security/mtls.yaml` | F1-11b y F09-92 |
| 8.21 | Seguridad de los servicios de red | mp.com.2 | implementada en desarrollo | `libs/tls/argos_tls/__init__.py`, `tests/integration/test_mtls.py` | — |
| 8.22 | Segregación en las redes | mp.com.4 | implementada en desarrollo | `deploy/dev/compose.yaml`, `tests/integration/test_ai_boundary.py` | — |
| 8.23 | Filtrado web | mp.s.3 | responsabilidad del organismo | — | El appliance no navega |
| 8.24 | Uso de la criptografía | mp.info.3, op.exp.10 | implementada en desarrollo | `services/evidence/argos_evidence/signing.py`, `libs/tls/argos_tls/__init__.py`, `tests/security/test_tls_verification.py` | Claves en el TPM con F07-15 |
| 8.25 | Ciclo de vida de desarrollo seguro | mp.sw.1 | implementada | `.github/workflows/ci.yml`, `docs/adr/0003-herramientas-y-ci.md` | — |
| 8.26 | Requisitos de seguridad de las aplicaciones | mp.sw.1 | implementada | `docs/seguridad/modelo-amenazas.md`, `docs/adr/0014-seguridad-de-plataforma.md` | — |
| 8.27 | Arquitectura segura y principios de ingeniería | op.pl.2 | implementada | `docs/adr/0014-seguridad-de-plataforma.md`, `tests/architecture/test_ai_boundary.py` | — |
| 8.28 | Codificación segura | mp.sw.1 | implementada | `tests/security/test_tls_verification.py`, `connectors/sdk/tests/test_sdk_readonly.py`, `.gitleaksignore` | Análisis estático, detección de secretos y validación de sentencias |
| 8.29 | Pruebas de seguridad en el desarrollo y la aceptación | mp.sw.2 | implementada | `tests/security/test_access_battery.py`, `docs/seguridad/bateria-accesos.md` | — |
| 8.30 | Desarrollo externalizado | op.ext.1 | responsabilidad del organismo | — | — |
| 8.31 | Separación de los entornos de desarrollo, prueba y producción | mp.sw.2 | implementada | `docs/adr/0014-seguridad-de-plataforma.md`, `tests/integration/test_keycloak_mfa.py` | Los secretos de desarrollo llevan la marca `dev-only-` y un test impide que salgan del realm de desarrollo |
| 8.32 | Gestión de cambios | op.exp.5 | implementada | `.github/workflows/ci.yml`, `docs/decisiones/README.md` | — |
| 8.33 | Información de pruebas | mp.info.1 | implementada | `docs/adr/0008-sujeto-sintetico.md`, `tests/integration/test_synthetic_subjects.py` | Solo datos sintéticos |
| 8.34 | Protección de los sistemas durante las pruebas de auditoría | op.ext.4 | implementada | `connectors/sdk/argos_connector/readonly.py`, `connectors/sdk/argos_connector/budget.py`, `connectors/sdk/tests/test_sdk_budget.py` | Los retos son de solo lectura y respetan un presupuesto de carga |
