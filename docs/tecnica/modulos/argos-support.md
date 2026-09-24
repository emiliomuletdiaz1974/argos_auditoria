---
id: MOD-argos-support
kind: module
title: Paquete de diagnóstico revisable (argos-support)
module: argos-support
phases: ["09"]
version: 0.1.0-alpha
commit: 34fc10a
date: 2026-09-24
status: current
confidentiality: client
---

# Paquete de diagnóstico revisable (argos-support)

## 1. Propósito

El soporte trabaja **sin acceso remoto**: el appliance no abre ninguna puerta al proveedor. Cuando hace falta ver qué pasa:

- el operador pide un paquete de diagnóstico;
- lo lee entero en la consola, con el índice y cada fichero tal como saldrán;
- solo entonces lo descarga, cifrado únicamente para la clave del soporte;
- lo envía él, por el canal que elija.

La regla del paquete es que **lo revisado es lo que sale**. Implementa ARG-088 (tarea F09-11; Pliego P-06; ADR-0014, punto 6; nota de desviación ARG-081-090).

## 2. Alcance y límites

- **Qué recoge:**
  - `versions.txt`: la versión instalada y la imagen de cada servicio;
  - `health.json`: el estado de salud de cada servicio y la última salida de su comprobación, que llama a `/health`;
  - `events.txt`: los eventos del ciclo de vida de los contenedores en las últimas 24 horas (creación, arranque, parada, muerte, OOM, cambios de salud);
  - `logs/<servicio>.log`: las últimas 500 líneas de cada servicio, con el número de depuraciones en la cabecera;
  - `journal-tail.json`: los últimos 200 asientos del diario (secuencia, actor, acción y fecha), **sin su carga**;
  - `config-names.txt`: los nombres de las variables de configuración y de los secretos montados, **nunca sus valores**;
  - `INDEX.json`: el contenido del paquete (nombre, tamaño, SHA-256 y depuraciones de cada fichero), la fecha y una nota para el operador en castellano.
- **Qué no recoge:**
  - nada de la base de datos de negocio;
  - nada de los sistemas del cliente: en desarrollo, las fuentes simuladas (`source-*`) quedan fuera, porque en el appliance son sistemas del cliente.
- **Qué no hace:**
  - no envía nada: la descarga la hace el operador;
  - la exportación a soporte físico es de la esclusa (F09-13).

## 3. Arquitectura

- **`collect(inspector, journal_tail, installed_version, generated_at) -> Preview`:**
  - recoge, depura e indexa;
  - la misma entrada da los mismos ficheros y el mismo índice, porque el orden y las fechas son fijos.
- **Depurador (`argos_support.scrub.Scrubber`).** Se aplica a **todo texto libre** del paquete: registros, salidas de salud, eventos, actores del diario, imágenes y nombres. En este orden:
  1. los valores de los secretos que el recolector ve en el entorno de cada servicio, enteros (por el nombre de la variable y las contraseñas dentro de URL);
  2. credenciales en URL, JWT, cabeceras `Bearer` y pares del tipo `password=…`;
  3. correos electrónicos, con un marcador estable por dirección;
  4. los identificadores españoles de los guardarraíles de ARG-060 (DNI, NIE, NUSS, IBAN). Solo se sustituye lo que valida, con la misma tabla (`library/prompts/guardrails.yaml`) y la misma función (`argos_connector.validators.scrub_identifiers`) que el gateway de IA.
- **`build_package(preview, approved_index_sha256, recipient)`:**
  - cifra solo si el índice aprobado es el de la vista previa y cada fichero sigue coincidiendo con su huella;
  - el archivo es un `tar.gz` determinista, con el índice primero;
  - el cifrado es `age` (`pyrage`) a la clave pública del soporte.
- **Inspectores (puerto `Inspector`, solo lectura).** Siempre con listas de argumentos y nunca `shell=True`:
  - `ComposeInspector`: `docker compose ps`, `docker inspect`, `docker compose logs` y `docker events` con ventana acotada;
  - `KubernetesInspector`: `kubectl get pods`, `kubectl logs` y `kubectl get events`.

  El puerto no puede desplegar nada, a diferencia del del actualizador. Un servicio sin registros deja una línea que lo dice y no detiene el paquete.
- **`DiagnosticsStore`**, la carpeta que comparten la API y el recolector:
  - `queue/` con las peticiones;
  - `previews/<id>/` con cada vista previa;
  - una vista previa editada en disco deja de coincidir con su índice y se rechaza.
- **Flujo:**
  1. la API encola la petición;
  2. el recolector, junto al orquestador, deja la vista previa;
  3. la API la muestra en claro;
  4. la API cifra la vista previa aprobada.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función | `collect(inspector, journal_tail, installed_version, generated_at) -> Preview` | Vista previa: ficheros e índice, sin cifrar |
| Función | `build_package(preview, approved_index_sha256, recipient) -> bytes` | Paquete cifrado; `DiagnosticsError` si el índice no es el aprobado o un fichero cambió |
| Función | `open_package(package, identity) -> dict[str, bytes]` | Lo que hace el soporte al recibirlo (y los tests) |
| Función | `archive(preview) -> bytes` | El `tar.gz` determinista que se cifra |
| Clase | `DiagnosticsStore(root)` | `request`, `pending`, `status`, `save` y `load` |
| Puerto | `Inspector` | `services`, `state`, `logs` y `events`; `ComposeInspector` y `KubernetesInspector` |
| CLI | `argos-support collect OUT`, `watch --store DIR [--once]`, `package PREVIEW --approve SHA --recipient FILE --out FILE` | `watch` recoge las peticiones que dejó la API |
| API | `POST /api/v1/support/diagnostics` (`support.diagnose`) | Encola la petición; `202` con el identificador |
| API | `GET /api/v1/support/diagnostics/{id}` (`support.diagnose`) | `collecting`, o la vista previa: índice, huella del índice y cada fichero en claro |
| API | `POST /api/v1/support/diagnostics/{id}/package` (`support.package`, con segundo factor) | El paquete cifrado para el índice aprobado; `422` si no coincide, `409` si aún se recoge |
| Consola | Sección «Soporte» | Muestra la nota, el índice y cada fichero; la descarga exige confirmar la lectura |

## 5. Configuración

- **CLI (variables de entorno):**
  - `ARGOS_COMPOSE_FILE` o `ARGOS_NAMESPACE`: el orquestador que se lee;
  - `ARGOS_DATABASE_URL`: la cola del diario;
  - `ARGOS_UPDATE_STATE`: la carpeta con la versión instalada.
- **API:** `ARGOS_SUPPORT_DIR` (con `queue/` y `previews/`) y `ARGOS_SUPPORT_RECIPIENT_FILE` (la clave pública `age` del soporte). Sin ellas, la API responde `503` a estas rutas.
- **Desarrollo:** `tools/dev_support.py` prepara `deploy/dev/support/` (ignorado por git) en cada `make dev`, con una clave de prueba del soporte generada al vuelo. El recolector corre en el anfitrión:

  ```
  ARGOS_COMPOSE_FILE=deploy/dev/compose.yaml ARGOS_UPDATE_STATE=deploy/dev/update \
  uv run argos-support watch --store deploy/dev/support
  ```

## 6. Seguridad y tratamiento de datos

- **Lo revisado es lo que sale.** El paquete se construye a partir de los bytes que la consola mostró, y solo para la huella del índice que el operador aprobó. Si un fichero cambió después, no hay paquete.
- **Sin valores de secretos.** El paquete recoge los nombres de las variables y de los secretos montados, no sus valores. Los valores de los secretos del entorno se sustituyen enteros en cualquier texto donde aparezcan. La prueba de integración comprueba que ningún valor de `argos/` en Vault aparece en ningún fichero de un paquete real.
- **Depuración de todo texto libre**, no solo de los registros, con los identificadores de ARG-060 más correos, tokens y credenciales. El paquete no importa la capa de IA (ADR-0012): la función de depuración vive en el SDK de conectores.
- **Nada de negocio.** Del diario solo salen secuencia, actor, acción y fecha. No se consulta ninguna tabla de negocio.
- **Solo el administrador de la plataforma.** Pedir y leer el paquete exige `support.diagnose`. Cifrarlo, que es lo que sale, exige `support.package` con segundo factor.
- **Todo queda registrado.** Petición, vista previa, paquete construido (con la huella del índice y la del paquete) y paquete rechazado van al diario y al registro de seguridad.
- **Sin shell.** Un test recorre el paquete y falla si alguna llamada usa `shell=True` u `os.system`.

## 7. Operación

- **Desde la consola:** «Soporte» → «Preparar un paquete de diagnóstico», leer cada fichero, confirmar y «Cifrar para el soporte y descargar».
- **Sin consola:**
  1. `argos-support collect DIR`;
  2. leer `DIR/previews/<id>/`;
  3. `argos-support package DIR/previews/<id> --approve <sha256 de INDEX.json> --recipient soporte.pub --out paquete.age`.
- **Lo que hace el soporte:** `age -d -i clave paquete.age | tar xz`, o `open_package`.

## 8. Verificación

- **`services/support/tests/test_diagnostics_pure.py`:**
  - un registro con DNI, IBAN y correo sale depurado;
  - un secreto plantado en el entorno no aparece en ningún fichero;
  - la depuración alcanza al diario, los eventos y la salud;
  - la cola del diario va sin carga;
  - el índice lista todo y solo lo que hay;
  - la misma entrada da el mismo índice y el mismo archivo;
  - otro índice, o un fichero cambiado, no da paquete;
  - el paquete se descifra con la clave de prueba y coincide con la vista previa;
  - el almacén detecta una vista previa editada y rechaza identificadores ajenos;
  - ninguna orden usa `shell=True`.
- **`services/support/tests/test_inspectors.py`:** órdenes como listas en Compose y Kubernetes, ventana de eventos acotada y sin `exec_*`, fuentes simuladas fuera y un servicio sin registros que no detiene el paquete.
- **`services/api/tests/test_support_diagnostics.py`:** encolar, vista previa en claro, paquete igual a lo revisado, `422` con otro índice o un fichero editado, `409` mientras se recoge, solo `platform_admin` y segundo factor para el paquete.
- **`tests/integration/test_diagnostics.py`**, contra el compose de desarrollo:
  - paquete real sin ningún valor de Vault;
  - cola del diario sin carga;
  - la API cifra lo revisado y la clave del soporte lo abre igual;
  - la ruta desplegada existe y exige token.
- **`console/src/views/support/support.test.tsx`:** la pantalla muestra la nota, el índice y cada fichero, no deja cifrar sin confirmar la lectura, envía la huella del índice mostrado y explica un rechazo.

## 9. Limitaciones conocidas y pendientes

- **El recolector de desarrollo corre en el anfitrión**, como el actualizador (nota ARG-086): necesita Docker Compose, que resuelve sus rutas en el cliente.
- **Los valores de configuración guardados en Vault que no son secretos**, como el host de una fuente, pueden aparecer en un registro si un servicio los escribe. El recolector no lee Vault y solo sustituye por valor los secretos que ve en el entorno. La prueba de integración excluye la dirección de loopback de las fuentes simuladas, que aparece en cada comprobación de salud.
- **La ruta desplegada solo se prueba cerrada.** El realm de desarrollo no tiene un usuario `platform_admin`, así que el recorrido completo con un token real se prueba con la aplicación en proceso.
- **La clave del soporte de desarrollo es de prueba.** En el appliance va la clave pública real del soporte, fijada en la imagen.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-24 | Recolector con inspectores de Compose y Kubernetes, depurador de todo texto libre, índice determinista, cifrado `age` solo del índice aprobado, API, consola y CLI | F09-11 (ARG-088) |
