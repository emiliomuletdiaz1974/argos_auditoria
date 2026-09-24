---
id: MOD-argos-example
kind: module
title: Servicio de ejemplo (argos-example)
module: argos-example
phases: ["01"]
version: 0.5.0-alpha
commit: 4f6309a
date: 2026-09-23
status: current
confidentiality: internal
---

# Servicio de ejemplo (argos-example)

## 1. Propósito

Servicio de referencia interno de la Fase 01 (ARG-001). Demuestra el patrón que siguen todos los servicios:
- arranque con la configuración común;
- salud uniforme;
- escritura y verificación del diario de auditoría;
- imagen de contenedor incluida en el manifiesto de release firmado.

No forma parte del producto que se entrega al cliente.

## 2. Alcance y límites

Solo demostración y pruebas: no trata datos del cliente ni se despliega en el appliance.

## 3. Arquitectura

Aplicación FastAPI con ciclo de vida que abre el diario y monta las rutas de salud de `argos-common`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| HTTP | `GET /health/live`, `GET /health` | Salud uniforme (comprobación de la base de datos) |
| HTTP | `POST /demo/entries?n=1..1000` | Escribe `n` asientos de demostración en el diario |
| HTTP | `GET /journal/verification` | Verifica la cadena completa y devuelve anomalías con su posición |
| Imagen | `argos-example:<versión>` | Construida con `make build` e incluida en `make manifest` |

## 5. Configuración

`ARGOS_DATABASE_URL`; en desarrollo escucha en `127.0.0.1:8001`. Desde F09-05, `ARGOS_DATABASE_URL` no lleva usuario (`postgresql://postgres:5432/argos?service=argos`), y `ARGOS_DATABASE_VAULT_ROLE` (`svc-example`) con `ARGOS_VAULT_APPROLE_DIR` dicen de dónde sale la credencial. La contraseña de la base llega en un fichero, `ARGOS_DATABASE_PASSWORD_FILE` (en desarrollo, `/run/secrets/db-example`, que genera `tools/dev_db_users.py`), y no en la cadena de conexión.

## 6. Seguridad y tratamiento de datos

- **TLS hacia PostgreSQL y NATS** (F09-06, ARG-083): el contenedor monta su propio certificado en `/run/tls`, que no monta ningún otro servicio. libpq verifica PostgreSQL (`verify-full`) y NATS exige el certificado del servicio.
- **Postura del contenedor** (F09-03, ARG-084, P-22): corre como `10001:10001`, sin capacidades (`cap_drop: [ALL]`), con la raíz de solo lectura y `/tmp` en `tmpfs`, sin escalada (`no-new-privileges`) y con el perfil seccomp por defecto de Docker. La imagen no lleva `bash`. En el compose lo exige `tests/security/test_compose_posture.py`, y `tests/integration/test_container_posture.py` lo comprueba dentro del contenedor en marcha.
- **Base de datos con mínimo privilegio** (F09-04, ARG-085): el servicio se conecta como `login_example`, miembro del rol `svc_example` (migración `0033`), y nunca como superusuario. El rol tiene solo las tablas y operaciones que usa su código; el diario se escribe únicamente con `argos.journal_append()`. Lo comprueban `tests/integration/test_service_roles.py` (la matriz `tests/fixtures/db_access_matrix.yaml` y el usuario de cada contenedor en marcha).
- **Credencial de base de datos efímera** (F09-05, ARG-085): el servicio entra con un usuario que Vault crea para él, miembro de ``svc_example``, válido 24 h y borrado al vencer. Lo renueva en caliente `argos_common.dynamic_db`. El AppRole con el que lo pide llega por volumen y no aparece en `docker inspect`.
Solo escribe asientos sintéticos de demostración en el diario.

## 7. Operación

Arranca con el entorno de desarrollo y se detiene limpiamente: registra `clean shutdown` en JSON y sale con código 0.

## 8. Verificación

- **Test de integración:** `tests/integration/test_example_service.py`.
- **Prueba de la Fase 1:** `tests/e2e/test_phase1_acceptance.py`. Se escriben 100 asientos a través del servicio; la corrupción en disco se detecta con su posición y, restaurada, la cadena vuelve a estar íntegra.

## 9. Limitaciones conocidas y pendientes

Ninguna: es un servicio de referencia.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Servicio de ejemplo con salud, diario y verificación | Fase 01 |
| 0.2.0-alpha | 2026-09-23 | Contenedor con la postura restringida de ARG-084 | F09-03 |
| 0.3.0-alpha | 2026-09-23 | Usuario de base `login_example` en `svc_example`: solo escribe el diario por su función | F09-04 (ARG-085) |
| 0.4.0-alpha | 2026-09-23 | Usuario de base efímero de Vault (`svc-example`), renovado en caliente | F09-05 (ARG-085) |
| 0.5.0-alpha | 2026-09-23 | TLS verificado hacia PostgreSQL y NATS con su propio certificado | F09-06 (ARG-083) |
