# Medidas del ENS (Real Decreto 311/2022, Anexo II) · categoría media

**Versión:** 1.0 · **Fecha:** 2026-09-24 · **Dossier de seguridad v1** · **Confidencialidad:** `client`

Una fila por medida del Anexo II. Los estados se explican en el [índice del dossier](README.md). Las rutas de la columna *Evidencia* son del repositorio del producto, y `tests/docs/test_security_dossier.py` comprueba que existen.

- **Aplicabilidad:** la tabla recoge todas las medidas. El organismo decide en su Declaración de Aplicabilidad cuáles aplican a su sistema en categoría media, y con qué refuerzos.
- **Implementada:** significa que está en el producto y probada. Que el despliegue del organismo la aplique es parte de su proceso de autorización (org.4).

## Marco organizativo

| Medida | Nombre | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|
| org.1 | Política de seguridad | responsabilidad del organismo | — | El producto aporta su arquitectura de seguridad: `docs/adr/0014-seguridad-de-plataforma.md` |
| org.2 | Normativa de seguridad | responsabilidad del organismo | — | El producto aporta sus reglas de uso en la documentación técnica (`docs/tecnica/`) |
| org.3 | Procedimientos de seguridad | responsabilidad del organismo | — | Los procedimientos de operación del producto están en cada documento de módulo, §7 |
| org.4 | Proceso de autorización | responsabilidad del organismo | — | Este dossier es la entrada técnica del proceso |

## Marco operacional

| Medida | Nombre | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|
| op.pl.1 | Análisis de riesgos | implementada | `docs/seguridad/modelo-amenazas.md`, `docs/seguridad/revision-f01-f08.md`, `tests/docs/test_threat_model.py` | STRIDE por superficie; el análisis del organismo sobre su sistema es suyo |
| op.pl.2 | Arquitectura de seguridad | implementada | `docs/adr/0014-seguridad-de-plataforma.md`, `docs/seguridad/dossier/00-descripcion-sistema.md` | — |
| op.pl.3 | Adquisición de nuevos componentes | implementada | `uv.lock`, `console/package-lock.json`, `tools/vuln_gate.py`, `platform/security/vex.yaml` | Dependencias fijadas y puerta de vulnerabilidades en cada release |
| op.pl.4 | Dimensionamiento / gestión de la capacidad | implementada en desarrollo | `tests/integration/test_inventory_benchmark.py`, `connectors/sdk/argos_connector/budget.py` | La medición en el hardware real es F06-98 |
| op.pl.5 | Componentes certificados | responsabilidad del organismo | — | La certificación del producto sigue el itinerario de F09-97 |
| op.acc.1 | Identificación | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `libs/auth/argos_auth/__init__.py`, `tests/integration/test_keycloak.py` | Identidad única por persona en Keycloak; el actor del diario es su `sub` |
| op.acc.2 | Requisitos de acceso | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/contract/test_api_authz.py`, `tests/security/test_access_battery.py` | Denegación por defecto; matriz rol × permiso versionada |
| op.acc.3 | Segregación de funciones y tareas | implementada | `services/api/argos_api/authz/permissions.yaml`, `tests/integration/test_separation_of_duties.py`, `tests/contract/test_api_authz.py` | Roles incompatibles y doble control por persona |
| op.acc.4 | Proceso de gestión de derechos de acceso | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `services/api/argos_api/authz/permissions.yaml` | Dar y retirar roles es un proceso del organismo en su Keycloak |
| op.acc.5 | Mecanismo de autenticación (usuarios externos) | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `tests/integration/test_keycloak_mfa.py`, `services/api/argos_api/sessions.py` | Segundo factor TOTP para los roles que deciden; bloqueo por fuerza bruta; sesión cerrada que invalida sus tokens |
| op.acc.6 | Mecanismo de autenticación (usuarios de la organización) | implementada en desarrollo | `deploy/dev/keycloak/realm-argos.json`, `tests/integration/test_keycloak_mfa.py`, `platform/image/harden.sh` | Acceso al sistema operativo solo con llave SSH por el bastión (F09-90) |
| op.exp.1 | Inventario de activos | implementada | `tools/sbom.py`, `libs/common/argos_common/release.py` | SBOM de cada imagen dentro del manifiesto firmado; el inventario físico es del organismo |
| op.exp.2 | Configuración de seguridad | pendiente de hardware | `platform/image/harden.sh`, `tests/platform/test_harden_idempotent.py`, `tests/security/test_compose_posture.py` | F09-90 (imagen endurecida y puntuación CIS ≥ 90 %); la postura de contenedores ya se prueba en el compose |
| op.exp.3 | Gestión de la configuración de seguridad | implementada | `platform/image/hardening-exceptions.yaml`, `tools/cis_gate.py`, `tests/tools/test_cis_gate.py`, `.github/workflows/ci.yml` | Configuración versionada; excepciones con justificación y responsable |
| op.exp.4 | Mantenimiento y actualizaciones de seguridad | implementada en desarrollo | `services/updater/argos_updater/__init__.py`, `tests/integration/test_updater.py`, `tools/vuln_gate.py` | Actualizador firmado y transaccional con vuelta atrás |
| op.exp.5 | Gestión de cambios | implementada | `.github/workflows/ci.yml`, `docs/decisiones/README.md`, `docs/desviaciones/ARG-086.md` | Cada cambio con prueba, registro de decisiones y notas de desviación |
| op.exp.6 | Protección frente a código dañino | pendiente de hardware | `libs/common/argos_common/release.py`, `services/updater/argos_updater/__init__.py` | Solo se ejecuta software firmado y verificado; la protección del sistema operativo es de F09-90 y la firma de imágenes en k3s de F09-92 |
| op.exp.7 | Gestión de incidentes | responsabilidad del organismo | — | El producto alerta: `deploy/dev/prometheus/rules/security.yml` |
| op.exp.8 | Registro de la actividad | implementada | `libs/common/argos_common/security_log.py`, `services/api/migrations/0036_security_log.sql`, `tests/integration/test_security_log.py`, `libs/common/argos_common/journal.py` | Diario encadenado de toda acción y registro de seguridad aparte, con su cadena |
| op.exp.9 | Registro de la gestión de incidentes | responsabilidad del organismo | — | — |
| op.exp.10 | Protección de claves criptográficas | pendiente de hardware | `services/evidence/argos_evidence/signing.py`, `tests/integration/test_signing.py` | Hoy, Vault transit con claves no exportables; en el appliance, TPM: F07-15 y F09-91 |
| op.ext.1 | Contratación y acuerdos de nivel de servicio | responsabilidad del organismo | — | — |
| op.ext.2 | Gestión diaria | responsabilidad del organismo | — | — |
| op.ext.3 | Protección de la cadena de suministro | implementada | `tools/sbom.py`, `tools/vuln_gate.py`, `libs/common/argos_common/release.py`, `tests/tools/test_vuln_gate.py` | SBOM y puerta de vulnerabilidades; releases firmadas y verificadas antes de aplicar |
| op.ext.4 | Interconexión de sistemas | implementada | `connectors/sdk/argos_connector/readonly.py`, `connectors/sdk/tests/test_sdk_readonly.py`, `services/airgap/argos_airgap/__init__.py` | Conexión con los sistemas del organismo solo de lectura; con el exterior, solo por la esclusa |
| op.nub.1 | Protección de servicios en la nube | responsabilidad del organismo | — | El producto no usa servicios en la nube: se ejecuta en las instalaciones |
| op.cont.1 | Análisis de impacto | responsabilidad del organismo | — | — |
| op.cont.2 | Plan de continuidad | responsabilidad del organismo | — | El producto aporta el backup: `docs/seguridad/backup-restauracion.md` |
| op.cont.3 | Pruebas periódicas | implementada en desarrollo | `platform/backup/restore_test.py`, `tests/integration/test_backup_restore.py`, `deploy/dev/prometheus/rules/backup.yml` | Prueba de restauración fechada, con alerta si caduca; temporizadores en el nodo con F09-92 |
| op.cont.4 | Medios alternativos | responsabilidad del organismo | — | — |
| op.mon.1 | Detección de intrusión | pendiente de hardware | `platform/image/audit/argos.rules`, `platform/k8s/security/mtls.yaml` | auditd y políticas de red en el appliance: F09-90 y F09-92 |
| op.mon.2 | Sistema de métricas | implementada en desarrollo | `services/api/argos_api/security_events.py`, `deploy/dev/prometheus/rules/security.yml`, `deploy/dev/prometheus/rules/backup.yml` | Métricas del registro de seguridad y de las pruebas de restauración |
| op.mon.3 | Vigilancia | implementada en desarrollo | `deploy/dev/prometheus/rules/security.yml`, `tests/security/test_access_battery.py` | Alertas de ráfagas de rechazos, cadena rota y firmas rechazadas |

## Medidas de protección

| Medida | Nombre | Estado | Evidencia | Tarea / nota |
|---|---|---|---|---|
| mp.if.1 | Áreas separadas y con control de acceso | responsabilidad del organismo | — | El appliance vive en la sala del organismo |
| mp.if.2 | Identificación de las personas | responsabilidad del organismo | — | — |
| mp.if.3 | Acondicionamiento de los locales | responsabilidad del organismo | — | — |
| mp.if.4 | Energía eléctrica | responsabilidad del organismo | — | — |
| mp.if.5 | Protección frente a incendios | responsabilidad del organismo | — | — |
| mp.if.6 | Protección frente a inundaciones | responsabilidad del organismo | — | — |
| mp.if.7 | Registro de entrada y salida de equipamiento | responsabilidad del organismo | — | Los soportes de la esclusa quedan en el diario: `services/airgap/argos_airgap/__init__.py` |
| mp.per.1 | Caracterización del puesto de trabajo | responsabilidad del organismo | — | — |
| mp.per.2 | Deberes y obligaciones | responsabilidad del organismo | — | — |
| mp.per.3 | Concienciación | responsabilidad del organismo | — | — |
| mp.per.4 | Formación | responsabilidad del organismo | — | — |
| mp.eq.1 | Puesto de trabajo despejado | responsabilidad del organismo | — | — |
| mp.eq.2 | Bloqueo de puesto de trabajo | responsabilidad del organismo | — | La consola cierra su sesión de verdad: `services/api/argos_api/sessions.py` |
| mp.eq.3 | Protección de dispositivos portátiles | responsabilidad del organismo | — | — |
| mp.eq.4 | Otros dispositivos conectados a la red | pendiente de hardware | `platform/image/harden.sh`, `platform/image/hardening-exceptions.yaml` | El appliance como dispositivo de la red del organismo: F09-90 y F1-11b |
| mp.com.1 | Perímetro seguro | pendiente de hardware | `platform/k8s/security/mtls.yaml`, `platform/k8s/security/verify-images.yaml` | Política de red por defecto en k3s: F1-11b y F09-92 |
| mp.com.2 | Protección de la confidencialidad | implementada en desarrollo | `libs/tls/argos_tls/__init__.py`, `tests/integration/test_mtls.py`, `tests/security/test_tls_verification.py` | mTLS interno y TLS verificado hacia los sistemas del organismo |
| mp.com.3 | Protección de la integridad y de la autenticidad | implementada en desarrollo | `libs/tls/argos_tls/__init__.py`, `tests/integration/test_mtls.py`, `libs/common/argos_common/release.py` | — |
| mp.com.4 | Separación de flujos de información en la red | implementada en desarrollo | `deploy/dev/compose.yaml`, `tests/integration/test_ai_boundary.py` | Redes separadas para la IA y la evidencia; en el appliance, políticas de red (F09-92) |
| mp.si.1 | Marcado de soportes | responsabilidad del organismo | — | — |
| mp.si.2 | Criptografía | pendiente de hardware | `platform/image/seal-disk.sh`, `platform/backup/backup_common.py`, `services/support/argos_support/__init__.py` | Disco cifrado sellado al TPM: F09-91; las copias (restic) y el diagnóstico (`age`) ya salen cifrados |
| mp.si.3 | Custodia | responsabilidad del organismo | — | — |
| mp.si.4 | Transporte | implementada en desarrollo | `services/airgap/argos_airgap/__init__.py`, `tests/integration/test_airgap.py` | Esclusa: lista cerrada de lo que sale, firma verificada de lo que entra, SHA-256 de todo |
| mp.si.5 | Borrado y destrucción | responsabilidad del organismo | — | — |
| mp.sw.1 | Desarrollo de aplicaciones | implementada | `.github/workflows/ci.yml`, `docs/adr/0003-herramientas-y-ci.md`, `docs/seguridad/revision-f01-f08.md`, `tests/security/test_tls_verification.py` | Pruebas primero, análisis estático, secretos vigilados y revisión de seguridad |
| mp.sw.2 | Aceptación y puesta en servicio | implementada | `Makefile`, `tests/security/test_access_battery.py`, `docs/seguridad/bateria-accesos.md` | — |
| mp.info.1 | Datos personales | implementada | `connectors/sdk/argos_connector/minimize.py`, `connectors/sdk/tests/test_sdk_minimize.py`, `services/support/argos_support/scrub.py` | Minimización en origen; solo datos sintéticos en desarrollo |
| mp.info.2 | Calificación de la información | responsabilidad del organismo | — | El producto clasifica los datos del inventario: `docs/tecnica/modulos/argos-inventory.md` |
| mp.info.3 | Firma electrónica | implementada en desarrollo | `services/evidence/argos_evidence/signing.py`, `tests/integration/test_signing.py`, `services/verifier/argos_verifier/api.py` | Firma Ed25519 de la raíz de campaña; clave en el TPM con F07-15 |
| mp.info.4 | Sellos de tiempo | implementada en desarrollo | `services/evidence/argos_evidence/tsa.py`, `tests/integration/test_tsa.py`, `tests/integration/test_airgap.py` | RFC 3161, también en modo aislado; TSA cualificada con F07-16 |
| mp.info.5 | Limpieza de documentos | implementada | `services/support/argos_support/scrub.py`, `services/support/tests/test_diagnostics_pure.py` | Lo que sale en un paquete de diagnóstico pasa por el depurador |
| mp.info.6 | Copias de seguridad | implementada en desarrollo | `platform/backup/backup.py`, `tests/integration/test_backup_restore.py`, `docs/seguridad/backup-restauracion.md` | — |
| mp.s.1 | Protección del correo electrónico | responsabilidad del organismo | — | El producto no envía correo |
| mp.s.2 | Protección de servicios y aplicaciones web | implementada | `services/api/argos_api/app.py`, `services/api/tests/test_same_origin.py`, `tests/security/test_access_battery.py` | Cabeceras de seguridad, mismo origen para mutaciones, problem+json sin trazas |
| mp.s.3 | Protección de la navegación web | responsabilidad del organismo | — | — |
| mp.s.4 | Protección frente a la denegación de servicio | implementada en desarrollo | `services/verifier/argos_verifier/api.py`, `connectors/sdk/argos_connector/budget.py` | Límites de tamaño en el comprobador público y presupuesto de carga hacia los sistemas del organismo |
