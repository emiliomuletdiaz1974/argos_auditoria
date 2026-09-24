---
id: MOD-argos-updater
kind: module
title: Actualizador firmado transaccional (argos-updater)
module: argos-updater
phases: ["09"]
version: 0.1.0-alpha
commit: c5fd428
date: 2026-09-24
status: current
confidentiality: client
---

# Actualizador firmado transaccional (argos-updater)

## 1. Propósito

Una actualización del appliance **o se completa entera o deja el sistema exactamente en la versión que tenía**. El actualizador:

- verifica todo el paquete antes de tocar nada;
- escribe en disco el plan para deshacer antes del primer paso;
- aplica por pasos con su deshacer;
- ante un fallo vuelve solo a la versión anterior, también si el propio proceso muere a mitad.

Implementa ARG-086 (tarea F09-10; Pliego P-02 y P-23; ADR-0014; nota de desviación ARG-086).

## 2. Alcance y límites

- **Qué aplica:** imágenes de los servicios, migraciones (compatibles con la versión anterior: expand-contract) y contenido normativo firmado (ARG-040), si el paquete lo trae.
- **Qué no aplica:** el arranque del sistema operativo (esquema A/B y resellado con el TPM, ARG-082). Eso es del appliance (F09-91).
- **Dónde corre:**
  - en desarrollo, en el anfitrión y con Docker Compose (nota ARG-086);
  - en el appliance, en el nodo y con Kubernetes (`KubernetesOrchestrator`), que hoy está escrito y probado con un doble.

## 3. Arquitectura

- **`verify_bundle(bundle, public_key, installed, allow_downgrade, content_key)`** comprueba, en este orden:
  1. la firma Ed25519 del manifiesto con la clave de release **fijada en el appliance**; una clave que viaje en el paquete no cuenta;
  2. que el manifiesto está en forma canónica;
  3. la versión, contra un patrón estricto;
  4. el anti-retroceso: una versión igual o anterior a la instalada se rechaza salvo `--allow-downgrade`, que queda registrado;
  5. la identidad de cada imagen exportada: el digest del índice OCI con cada blob comprobado, o el de la configuración en el formato clásico;
  6. los hashes de SBOM e informes de vulnerabilidades (`verify_release_files`, F09-09);
  7. si hay contenido, su firma propia (ARG-040).
- **`Updater.apply(bundle)`:**
  - verifica;
  - guarda el plan inverso (`plan.json`) antes de empezar;
  - ejecuta los pasos (`Step(name, do, undo, verify)`): imágenes, migraciones, cada servicio con su salud vigilada y contenido;
  - apunta en el plan la imagen anterior de cada servicio antes de cambiarlo;
  - si falla, deshace en orden inverso;
  - si todo va bien, escribe la versión instalada y borra el plan.
- **`Updater.recover()`:** al arrancar, un plan que sigue en disco es una actualización interrumpida; devuelve cada servicio cambiado a su imagen anterior.
- **Orquestadores**, siempre con listas de argumentos y nunca `shell=True`:
  - `ComposeOrchestrator`: `docker load`, `docker tag` sobre la imagen que usa el compose y `docker compose up -d --no-deps --force-recreate` de ese servicio;
  - `KubernetesOrchestrator`: `k3s ctr images import`, `kubectl set image` y `kubectl rollout status`.
- **`argos_updater.cli`** (`argos-update verify|apply|recover|watch`): el registro de cada paso va al diario (actor `system:updater`) y al registro de seguridad (F09-08).

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función | `verify_bundle(bundle, public_key, installed, allow_downgrade=False, content_key=None) -> VerifiedBundle` | Todo verificado, nada tocado; `UpdateRejectedError` si algo no cuadra |
| Clase | `Updater(state_dir, public_key, orchestrator, services, record, health_timeout, migrate, load_content, content_key)` | `verify`, `apply`, `recover` e `installed_version` |
| Puerto | `Orchestrator` | `load_images`, `current_image`, `deploy` y `healthy` |
| Clases | `ComposeOrchestrator(compose_file)` y `KubernetesOrchestrator(namespace)` | Desarrollo y appliance |
| CLI | `argos-update verify BUNDLE`, `apply BUNDLE [--allow-downgrade]`, `recover`, `watch --inbox --queue` | `watch` aplica las peticiones que dejó la API |
| API | `POST /api/v1/system/updates` (`system.update`: `platform_admin` con segundo factor) | Verifica con la clave fijada y encola; responde `202` |
| Herramienta | `tools/release.py bundle` | Paquete: manifiesto y firma, SBOM, imágenes por el id firmado y migraciones |

## 5. Configuración

- **CLI (variables de entorno):**
  - `ARGOS_UPDATE_STATE`: carpeta de estado, con la versión y el plan;
  - `ARGOS_RELEASE_PUBLIC_KEY`: la clave fijada;
  - `ARGOS_CONTENT_PUBLIC_KEY`: la clave de contenido;
  - `ARGOS_COMPOSE_FILE` o `ARGOS_NAMESPACE`: el orquestador que se usa;
  - `ARGOS_DATABASE_URL`: diario, registro de seguridad y migraciones.
- **API:** `ARGOS_UPDATE_DIR` (con `inbox/`, `queue/` y `version`) y `ARGOS_RELEASE_PUBLIC_KEY_FILE`.
- **Desarrollo:** `tools/dev_update.py` prepara `deploy/dev/update/` (ignorado por git) y toma la clave de release de Vault transit en cada `make dev`.

## 6. Seguridad y tratamiento de datos

- **Nada se aplica sin verificar.** La API y la CLI llaman a `verify_bundle`, y `apply` verifica por su cuenta aunque la petición venga de la API.
- **La clave no viaja con lo que verifica.** Un paquete firmado con otra clave, aunque la incluya, se rechaza.
- **Un paquete rechazado no deja rastro en el sistema.** Firma ausente o de otra clave, manifiesto alterado, imagen distinta de la firmada, SBOM cambiado o versión anterior: los tests comprueban que no hay ninguna llamada al orquestador.
- **Una versión maliciosa no llega a ninguna orden.** Algo como `0.2.0;rm` no pasa el patrón.
- **Cada paso queda registrado.** Verificación, pasos, aplicación, vuelta atrás, recuperación y bajada de versión van al diario y al registro de seguridad.
- **La API solo encola nombres.** La petición nombra un paquete de la bandeja, y el actualizador lo busca en la suya; un nombre que saldría de la bandeja se rechaza (`422`).

## 7. Operación

- **Actualizar:** el paquete llega a la bandeja; `argos-update apply` o la petición de la API con `watch`.
- **Tras una caída:** `argos-update recover` antes de nada (`apply` y `watch` lo hacen solos).
- **Bajar de versión:** solo con `--allow-downgrade`, y queda en el diario.

## 8. Verificación

- **`services/updater/tests/test_updater_pure.py`**, con un orquestador falso:
  - rechazos sin ninguna llamada al orquestador;
  - vuelta atrás en orden inverso;
  - proceso muerto a mitad, que `recover` devuelve a la versión anterior;
  - anti-retroceso y bajada explícita;
  - identidad de imágenes OCI y clásicas.
- **`services/updater/tests/test_orchestrators.py`:** órdenes como listas; Kubernetes con un doble.
- **`services/api/tests/test_update_requests.py`:** la ruta verifica y encola, y rechaza otra clave, una versión anterior o un nombre fuera de la bandeja.
- **`tests/integration/test_updater.py`**, contra el compose real y firmado con la clave de release de desarrollo:
  - un paquete bueno sube la versión del servicio de ejemplo;
  - uno cuya imagen nunca queda sana vuelve solo a la buena;
  - el diario y el registro de seguridad tienen los asientos.

## 9. Limitaciones conocidas y pendientes

- **El actualizador de desarrollo no tiene contenedor.** Docker Compose resuelve las rutas de los volúmenes en el cliente, y desde un contenedor en Docker Desktop no existen (nota ARG-086).
- **Sin rol de base propio.** En desarrollo usa la conexión de administración (asienta como `system:updater` y aplica migraciones); el rol queda en pendientes.
- **Ejecutar la cola de la API no tiene prueba propia.** La ruta encola y `watch` aplica lo encolado, pero ningún test recorre los dos extremos juntos.
- **El arranque A/B y el resellado con el TPM** son del appliance (F09-91).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-24 | Verificación completa previa, plan inverso en disco, pasos con deshacer, recuperación, orquestadores Compose y Kubernetes, CLI y petición por la API | F09-10 (ARG-086) |
