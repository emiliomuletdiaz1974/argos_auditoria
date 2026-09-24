---
id: MOD-argos-tls
kind: module
title: TLS mutuo entre servicios (argos-tls)
module: argos-tls
phases: ["09"]
version: 0.1.0-alpha
commit: pendiente
date: 2026-09-23
status: current
confidentiality: client
---

# TLS mutuo entre servicios (argos-tls)

## 1. Propósito

Cifrado y autenticación mutua de las comunicaciones internas de ARGOS (Pliego P-22, «comunicaciones internas cifradas con autenticación mutua»):

- los dos extremos de cada enlace presentan un certificado de la CA interna y exigen el del otro;
- solo se habla TLS 1.3;
- el certificado se renueva sin reiniciar el servicio.

Implementa ARG-083 (tarea F09-06).

## 2. Alcance y límites

- **Enlaces cubiertos:**
  - HTTP entre servicios de ARGOS: la API llama al gateway de IA;
  - PostgreSQL: solo `hostssl`, y el cliente verifica el servidor (`verify-full`);
  - NATS: TLS con certificado de cliente obligatorio.
- **Fuera de alcance:**
  - la consola y la API pública, que siguen detrás del puerto publicado en `127.0.0.1`: el TLS de cara al usuario es de la Fase 10;
  - el software de terceros del entorno de desarrollo (Temporal, Keycloak, OPA, la TSA y el EDC simulados), que sigue en claro dentro de la red de Docker (ver §9).
- **Emisión de certificados:**
  - la hace `argos_tls.issuer` en desarrollo;
  - en el appliance la hace cert-manager con la misma CA (`platform/k8s/security/mtls.yaml`), y aplicarlo es F09-92.

## 3. Arquitectura

- **`ReloadingTLS(server, cert_dir)`:** construye el contexto TLS de un extremo a partir de `tls.crt`, `tls.key` y `ca.crt`, con TLS 1.3 como mínimo y certificado obligatorio en los dos papeles.
  - En el **servidor**, `sni_callback` sustituye el contexto en cada apretón de manos si los ficheros cambiaron (vigilancia por `mtime`, como mucho cada `check_interval` segundos). Funciona también cuando el cliente no envía SNI.
  - En el **cliente**, `context()` devuelve el contexto al día.
  - Si el certificado está a medio escribir, se sigue con el anterior y se vuelve a mirar.
- **`mtls_client` y `mtls_async_client`:** clientes `httpx` con el certificado del servicio y la CA interna.
- **`serve(app, host, port, cert_dir)`:** ejecuta una aplicación ASGI con `uvicorn` exigiendo certificado de cliente.
- **`argos_tls.issuer`** (`python -m argos_tls.issuer`, contenedor `cert-issuer`):
  - pide a `pki_int/issue/argos-svc` un certificado por servicio (30 días), con su nombre DNS más `localhost` y `127.0.0.1`;
  - lo renueva a los dos tercios de su vida (día 20), y antes si la CA raíz cambió;
  - lo escribe de forma atómica en la carpeta de ese servicio: clave `0600`, certificado y CA `0644`.
- **PostgreSQL** (`deploy/dev/postgres/tls-entrypoint.sh`) y **NATS** (`deploy/dev/nats/run.sh`) copian o releen su certificado al renovarse y recargan sin cortar las conexiones.

Dependencias: `httpx` y `cryptography`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Clase | `ReloadingTLS(server: bool, cert_dir, check_interval=5.0)` | `context() -> ssl.SSLContext` |
| Función | `mtls_client(cert_dir, **kwargs) -> httpx.Client` | Cliente HTTP con TLS mutuo |
| Función | `mtls_async_client(cert_dir, **kwargs) -> httpx.AsyncClient` | Variante asíncrona |
| Función | `serve(app, host, port, cert_dir, **kwargs)` | `uvicorn` con certificado de cliente obligatorio |
| Constantes | `CERT_FILE`, `KEY_FILE`, `CA_FILE` | `tls.crt`, `tls.key`, `ca.crt` |
| Proceso | `python -m argos_tls.issuer` | Emisión y renovación desde Vault |

## 5. Configuración

- **Servicios:**
  - `ARGOS_TLS_DIR` (de `argos-common`): carpeta con su certificado. En el compose es `/run/tls`, un volumen `tmpfs` que solo montan ese servicio y `cert-issuer`.
  - la cadena de conexión de ARGOS lleva `sslmode=verify-full&sslrootcert=/run/tls/ca.crt`: libpq verifica PostgreSQL. No se usa `PGSSLMODE`, porque una variable de entorno llegaría también a las conexiones de los conectores con las fuentes del cliente, cuyo TLS decide cada conector (F09-31).
  - `ARGOS_NATS_URL=tls://nats:4222`.
- **Emisor:**
  - `ARGOS_TLS_SERVICES` (`carpeta=nombre[,nombre…];…`), `ARGOS_TLS_ROOT` y `ARGOS_TLS_CHECK_SECONDS` (60);
  - `VAULT_ADDR` y `VAULT_APPROLE_DIR`, con un AppRole que solo puede emitir de `pki_int/issue/argos-svc`.
- **Host de desarrollo:**
  - `tools/dev_tls.py` emite en cada `make dev` el certificado `argos-dev` en `deploy/dev/secrets/tls-host/` (ignorado por git);
  - el `Makefile`, `.env.example` y el `conftest` de los tests exportan `ARGOS_TLS_DIR`, y `ARGOS_DATABASE_URL` de `.env.example` verifica PostgreSQL con la CA del host. Los tests se conectan con el modo por defecto de libpq, que negocia TLS; que el servidor se verifica lo prueba `test_mtls.py`.

## 6. Seguridad y tratamiento de datos

- **Sin excepciones.** Ningún extremo acepta un par sin certificado ni uno firmado por otra CA. En el código y la configuración del producto no hay `verify=False`, `CERT_NONE` ni un `sslmode` explícito inferior a `verify-full`; lo vigila `tests/security/test_tls_verification.py`.
- **Aislamiento de las claves.** La clave privada de cada servicio solo la ve ese servicio: cada certificado vive en su propio volumen, que no monta ningún otro contenedor. `test_mtls.py` comprueba que cada contenedor tiene su propio certificado.
- **NATS (SEC-026, revisión F09-02).**
  - Cada usuario de servicio solo puede consultar, crear y confirmar sus propios consumidores (`$JS.API.CONSUMER.*.<stream>.<durable>`, `$JS.ACK.<stream>.<durable>.>`).
  - Ningún usuario de servicio crea, cambia ni borra un stream: eso lo hace el usuario `platform` una sola vez al arrancar (`tools/nats_streams.py`).
  - El inventario ya no publica en `argos.campaign.>`.
- **PostgreSQL.** Una conexión sin TLS se rechaza (`hostnossl … reject`), también la del superusuario. El motor de base de datos de Vault verifica el servidor con la misma CA.

## 7. Operación

- **Renovación.** Es automática, sin reinicios: el emisor revisa cada 60 s y los servicios toman el certificado nuevo en el siguiente apretón de manos.
- **Reinicio de Vault en desarrollo.** Vault genera otra CA; el emisor lo detecta y reemite todo. Un `make dev` lo deja todo al día.

## 8. Verificación

- **`libs/tls/tests/test_reloading.py`**, con una CA de prueba y un servidor TLS real:
  - rechaza un cliente sin certificado o de otra CA, y el cliente rechaza un servidor de otra CA;
  - nada por debajo de TLS 1.3;
  - un certificado sustituido en disco se sirve sin reinicio;
  - renovación a dos tercios y lectura de la especificación de servicios.
- **`tests/integration/test_mtls.py`**, contra el entorno:
  - el gateway no responde sin certificado y sí a la API;
  - cada contenedor tiene su certificado;
  - PostgreSQL rechaza una conexión sin TLS, y el cliente rechaza una CA ajena;
  - la conexión va en TLS 1.3;
  - NATS rechaza un cliente sin certificado;
  - permisos de NATS por usuario (SEC-026), con sondas que no cambian nada aunque el permiso existiera.
- **`tests/security/test_k8s_manifests.py`:** el `ClusterIssuer` y los `Certificate` de k3s.

## 9. Limitaciones conocidas y pendientes

- **Terceros en claro dentro de la red de desarrollo.** Temporal, Keycloak, OPA, la TSA y el EDC simulados no van con TLS mutuo. En el appliance, Temporal y OPA se configuran con certificados de cert-manager (F09-92).
- **Confirmaciones de NATS sin prueba directa.** El permiso de confirmación (`$JS.ACK`) de cada usuario no se prueba directamente: haría falta consumir mensajes reales del consumidor del servicio. Lo ejercitan las pruebas de extremo a extremo de los workers.
- **`secret_id` de larga vida en desarrollo.** El AppRole de `cert-issuer` tiene un `secret_id` de larga vida en desarrollo; en k3s lo sustituye Kubernetes auth (F09-92).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-23 | TLS mutuo 1.3 con recarga sin reinicio, emisor desde Vault, PostgreSQL y NATS con TLS, permisos de NATS por servicio | F09-06 (ARG-083) |
