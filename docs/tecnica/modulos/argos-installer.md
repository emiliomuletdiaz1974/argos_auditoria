---
id: MOD-argos-installer
kind: module
title: Instalador de la semana 1 (argos-installer)
module: argos-installer
phases: ["10"]
version: 0.3.0-alpha
commit: 6c030a9
date: 2026-09-28
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
- **La comprobación de sala** (ARG-097, F10-11) es el segundo paso, `site`, y tiene su propia lista previa al envío.

## 3. Arquitectura

- **`InstallConfig`:** la configuración (`platform/operation/installer.example.yaml` es el ejemplo). Cada valor se valida por lo que dice ser antes de llegar a ninguna orden: direcciones IPv4, nombre de interfaz, dispositivo en `/dev`, nombre de usuario, nombre de host, URL.
- **`Step(key, title, plan, verify)`:**

| Paso | Qué ejecuta | Cómo lo verifica |
|---|---|---|
| `network` | `netplan set`, `netplan apply` | la pasarela y el bastión responden a `ping` |
| `site` | nada: solo mide | la sala es `fit` para la talla (ver abajo) |
| `time` | servidor NTP del organismo y `timedatectl` | `NTPSynchronized` = `yes`; en aislado, la deriva declarada queda en el informe |
| `disk` | `platform/image/seal-disk.sh` (F09-14) | `cryptsetup luksDump` muestra un slot TPM2 |
| `admin` | `kcadm.sh` crea el usuario con TOTP y cambio de clave obligados, y le da `platform_admin` | el usuario aparece en el realm |
| `idp` | `kcadm.sh` crea el proveedor OIDC, si hay | el proveedor existe; si no hay, «omitida» |
| `tsa` | nada | la TSA responde; en aislado, «modo aislado explícito» |

- **`Installer`:**
  - recorre los pasos en orden y se detiene en el primero que no verifica;
  - guarda los pasos hechos en `state.json` y, al volver a ejecutarse, reanuda desde el que falló;
  - en ejecución en seco no ejecuta nada ni escribe estado: devuelve las órdenes que ejecutaría.
- **`site_check`, la comprobación de sala (ARG-097):**
  - mide con `ipmitool sensor list` (temperatura de entrada, fuentes, potencia y tensión), `ethtool <interfaz de datos>`, `ping` al bastión y a cada fuente declarada, y `nvidia-smi` (GPU y memoria);
  - cada analizador es una función pura sobre el texto de su orden;
  - compara con los límites de la talla (`platform/operation/sizes.yaml`, clave `site`) y da cada comprobación como `fit`, `unfit` o `not_measured`, con su motivo;
  - una orden que no está es `not_measured`, nunca `fit`; el paso solo pasa si todas son `fit`;
  - una fuente cuenta si el estado de su sensor dice presente y sin fallo (`na` no cuenta); una potencia `na` deja la suma sin medir; solo las tensiones de los sensores de cada fuente (`PS1 Voltage`) son la tensión de red, no los raíles de la placa; un ping con pérdida no es apto; se lee la salida de busybox; un enlace activo con velocidad desconocida es `not_measured`, no «caído» (QA-075, 076, 077, 087);
  - `prerequisites(talla)` da la lista previa al envío (rack, potencia y circuitos, BTU/h, tomas, SAI, climatización y red).
- **Órdenes:** siempre listas de argumentos. Un test recorre el código y falla si aparece `shell=`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| CLI | `argos-install --config <yaml> [--dry-run] [--state-dir <dir>]` | Instala o muestra el plan; código 1 si se detuvo |
| CLI | `argos-install --prerequisites S\|M\|L [--sizes <yaml>]` | Imprime la lista previa de la sala para esa talla |
| Configuración | `site: {size, data_interface, sources, limits_file}` | Talla, interfaz de datos y fuentes declaradas (IPv4) de la comprobación de sala |
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
- **La clave de recuperación llega a la persona y no al informe (QA-072).** El sellado del disco es una orden `to_console`: corre en la consola del operador sin capturar su salida, así que la clave se ve en pantalla una vez y nunca entra en el informe ni en el estado. El paso del disco se verifica antes de ejecutarse y, si el volumen ya está sellado, no se vuelve a sellar: cada sellado añadiría otra clave de recuperación.
- **El administrador se comprueba con lo que dice Keycloak (QA-081):** la salida de `kcadm.sh` se lee como JSON (con el formato de Jackson, espacio antes de los dos puntos), y el paso solo verifica si el usuario existe, tiene `CONFIGURE_TOTP` y `UPDATE_PASSWORD` como acciones obligadas y el rol `platform_admin`.
- **El informe suma todas las ejecuciones (QA-083).** El estado guarda la huella de la configuración y las entradas de cada paso, con su hora. Al reanudar, el informe firmado lleva también lo que hicieron las ejecuciones anteriores, por ejemplo la sala. Con otra configuración no cuenta nada de lo hecho: la instalación empieza de nuevo.
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

`services/installer/tests/test_site_check.py`:
- cada analizador con su salida de referencia (`tests/fixtures/site/`);
- sala sana apta para la S y no apta para la M por el enlace;
- sala caliente con una sola fuente, GPU pequeña y fuente inalcanzable: `unfit` con su motivo;
- cada orden ausente da «no medido», nunca «apto»;
- la lista previa y su CLI.

`services/airgap/tests/test_installation_export.py`: el informe sale por la esclusa solo si está firmado.

## 9. Limitaciones conocidas y pendientes

- **Sin hardware:** no se ha ejecutado contra el hardware real. Los pasos que tocan la red, el disco y el TPM se prueban con dobles (F10-90).
- **Referencias de `ipmitool` y `nvidia-smi` escritas, no capturadas:** siguen el formato documentado; F10-91 las sustituye por capturas del equipo real.
- **Keycloak:** `kcadm.sh` debe tener una sesión de administración del realm antes del paso `admin`. El runbook de campo de F10-90 lo dirá.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-25 | Primera versión | F10-10 (ARG-096) |
| 0.2.0-alpha | 2026-09-25 | Comprobación de sala: paso `site`, analizadores, límites por talla y lista previa | F10-11 (ARG-097) |
| 0.3.0-alpha | 2026-09-28 | Clave de recuperación en la consola, disco sellado una sola vez, administrador comprobado en JSON, informe acumulado y ligado a la configuración, y sala sin falsos aptos | QA-21 (QA-072, 075, 076, 077, 081, 083, 087) |
