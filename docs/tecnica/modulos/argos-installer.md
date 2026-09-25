---
id: MOD-argos-installer
kind: module
title: Instalador de la semana 1 (argos-installer)
module: argos-installer
phases: ["10"]
version: 0.1.0-alpha
commit: 96b3236
date: 2026-09-25
status: current
confidentiality: client
---

# Instalador de la semana 1 (argos-installer)

## 1. Propósito

Convierte «caja en el rack» en «sistema listo para conectar fuentes» en una jornada, siguiendo una configuración que el organismo revisa y firma antes. Implementa ARG-096 (tarea F10-10; Pliego P-26; ADR-0015, punto 9).

Cada paso planifica sus órdenes, las ejecuta y verifica el resultado. Un paso solo cuenta como hecho cuando su verificación pasa. El informe de instalación firmado abre el expediente de implantación del Pliego.

## 2. Alcance y límites

- **Qué hace:** red de gestión y bastión, hora, sellado del disco, primer administrador, federación opcional con el proveedor de identidad y autoridad de sellado o modo aislado.
- **Qué no hace:**
  - no es una interfaz a pantalla completa: es una CLI guiada, porque el CPD no siempre tiene pantalla y un YAML revisable es lo que el organismo aprueba;
  - no guarda contraseñas: el primer administrador configura su segundo factor y su clave en el primer acceso.
- **La comprobación de sala** (ARG-097) es un paso aparte (F10-11).

## 3. Arquitectura

- **`InstallConfig`:** la configuración (`platform/operation/installer.example.yaml` es el ejemplo). Cada valor se valida por lo que dice ser antes de llegar a ninguna orden: direcciones IPv4, nombre de interfaz, dispositivo en `/dev`, nombre de usuario, nombre de host, URL.
- **`Step(key, title, plan, verify)`:**

| Paso | Qué ejecuta | Cómo lo verifica |
|---|---|---|
| `network` | `netplan set`, `netplan apply` | la pasarela y el bastión responden a `ping` |
| `time` | servidor NTP del organismo y `timedatectl` | `NTPSynchronized` = `yes`; en aislado, la deriva declarada queda en el informe |
| `disk` | `platform/image/seal-disk.sh` (F09-14) | `cryptsetup luksDump` muestra un slot TPM2 |
| `admin` | `kcadm.sh` crea el usuario con TOTP y cambio de clave obligados, y le da `platform_admin` | el usuario aparece en el realm |
| `idp` | `kcadm.sh` crea el proveedor OIDC, si hay | el proveedor existe; si no hay, «omitida» |
| `tsa` | nada | la TSA responde; en aislado, «modo aislado explícito» |

- **`Installer`:**
  - recorre los pasos en orden y se detiene en el primero que no verifica;
  - guarda los pasos hechos en `state.json` y, al volver a ejecutarse, reanuda desde el que falló;
  - en ejecución en seco no ejecuta nada ni escribe estado: devuelve las órdenes que ejecutaría.
- **Órdenes:** siempre listas de argumentos. Un test recorre el código y falla si aparece `shell=`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| CLI | `argos-install --config <yaml> [--dry-run] [--state-dir <dir>]` | Instala o muestra el plan; código 1 si se detuvo |
| Informe | `installation-report.json` y `.sig` | Esquema `argos/installation/1`: pasos, detalle, códigos de salida y huella de la configuración; firmado con Ed25519 |
| Diario | `install.completed` / `install.stopped` | Con la huella del informe y el paso en que se detuvo |
| Esclusa | tipo de exportación `installation` | Saca el informe y su firma (F09-13, `argos-airgap`) |

## 5. Configuración

| Variable | Qué es |
|---|---|
| `ARGOS_VAULT_ADDR` y `ARGOS_INSTALL_VAULT_TOKEN_FILE` | Vault transit y el fichero con el token con el que se firma el informe (clave `argos-release`) |
| `ARGOS_DATABASE_URL` | El diario, donde queda la instalación |
| `ARGOS_INSTALL_DIR` (en la API) | Dónde dejó el instalador su estado; la esclusa exporta el informe desde ahí |

## 6. Seguridad y tratamiento de datos

- **Sin shell:** cada valor de la configuración se valida antes de formar parte de una orden, y las órdenes nunca pasan por un intérprete. Los tests prueban que un `;` o un `&&` en una dirección, una interfaz, un usuario o un servidor NTP se rechazan.
- **Sin contraseñas:** el administrador se crea sin clave y con el cambio de clave y el TOTP obligados.
- **Token de firma en fichero:** nunca en una variable.
- **Informe firmado:** con la clave de release, que no sale de Vault. Cualquiera con la clave pública verifica que es el que el appliance emitió.

## 7. Operación

La jornada de instalación y el runbook de campo llegan con el hardware (F10-90). Mientras tanto se prueba con dobles de cada orden.

## 8. Verificación

`services/installer/tests/test_installer_pure.py`:
- orden de los pasos;
- detención en el primero que falla y reanudación;
- ejecución en seco sin cambios;
- informe firmado que verifica;
- modo aislado;
- valores maliciosos rechazados;
- sin `shell=`;
- el ejemplo del repositorio es válido;
- ejecución en seco de la CLI.

`services/airgap/tests/test_installation_export.py`: el informe sale por la esclusa solo si está firmado.

## 9. Limitaciones conocidas y pendientes

- **Sin hardware:** no se ha ejecutado contra el hardware real. Los pasos que tocan la red, el disco y el TPM se prueban con dobles (F10-90).
- **Keycloak:** `kcadm.sh` debe tener una sesión de administración del realm antes del paso `admin`. El runbook de campo de F10-90 lo dirá.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-25 | Primera versión | F10-10 (ARG-096) |
