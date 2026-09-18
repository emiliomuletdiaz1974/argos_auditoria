---
id: MOD-argos-common
kind: module
title: Librería común de la plataforma (argos-common)
module: argos-common
phases: ["01", "03"]
version: 0.1.0-alpha
commit: 3c68e19
date: 2026-09-18
status: current
confidentiality: client
---

# Librería común de la plataforma (argos-common)

## 1. Propósito

Base compartida por todos los servicios de ARGOS: configuración validada al arrancar, errores tipados, registro estructurado, comprobación de salud, identificadores, **diario de auditoría encadenado**, migraciones auditables, acceso a secretos y firma de la release. Implementa los componentes ARG-001, ARG-005, ARG-009 y ARG-010.

## 2. Alcance y límites

- Ofrece piezas de infraestructura; no contiene lógica de negocio normativa ni accede a sistemas del cliente.
- El diario solo admite añadir asientos: la base de datos rechaza modificar, borrar o truncar.
- El almacén de secretos sellado por TPM está declarado, pero no implementado todavía (ver §9).

## 3. Arquitectura

| Submódulo | Responsabilidad |
|---|---|
| `config` | `ArgosConfig`: configuración tipada desde variables `ARGOS_*` o `.env`; un servicio mal configurado no arranca |
| `errors` | Jerarquía `ArgosError` con código y detalles serializables |
| `logs` | Registro JSON con campos obligatorios |
| `health` | Rutas uniformes `/health/live` y `/health` para servicios HTTP |
| `ids` | Identificadores UUID v7 ordenables en el tiempo |
| `journal` | Diario encadenado v1: canonicalización, hash y verificación independientes de la base de datos |
| `journal_pg` | Cliente PostgreSQL del diario: añadir, leer y verificar |
| `migrations` | Migrador de SQL numerado con suma de control y un asiento por migración |
| `secret_stores` | Interfaz única de secretos: Vault, fichero cifrado (solo desarrollo) y TPM (pendiente) |
| `release` | Manifiesto de release canónico y firma Ed25519 en Vault Transit |

Dependencias externas: PostgreSQL 16 (esquema `argos`), HashiCorp Vault (kv-v2 y Transit), pydantic-settings, psycopg 3, hvac y cryptography.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función | `load_config()`, `get_config()` | Construyen y validan la configuración; los errores nunca incluyen los valores recibidos |
| Función | `configure_logging(service, level, stream)`, `get_logger(name, component)` | Registro JSON con `timestamp`, `level`, `service`, `component`, `logger` y `message`; opcionales `journal_seq`, `trace_id` y `campaign_id` |
| Función | `mount_health(app, service, version, checks, timeout)` | `GET /health/live` (proceso) y `GET /health` (dependencias: 200 u 503 con `status` `ok` o `degraded`) |
| Función | `uuid7()` | Identificador UUID v7 (RFC 9562) |
| Clase | `PostgresJournal(dsn)` | `append(actor, action, payload, conn=None)`, `read(from_seq, to_seq)`, `verify(from_seq, to_seq)`, `head()` |
| Funciones | `canonicalize`, `compute_hash`, `verify_entries`, `require_integrity` | Recalculan y verifican la cadena sin confiar en la base de datos |
| Función | `apply_migrations(dsn, directory)` | Aplica migraciones `NNNN_nombre.sql` bajo bloqueo consultivo; `tools/migrate.py` |
| Clases | `VaultSecretStore(url, token, mount)`, `EncryptedFileSecretStore`, `TpmSecretStore` | Lectura de secretos por ruta |
| Funciones y clases | `build_manifest`, `serialize`, `VaultTransitSigner`, `verify_signature`, `key_fingerprint`, `require_trusted_key` | Manifiesto de release firmado; `tools/release.py build`, `sign` y `verify` (este exige `--fingerprint` o `ARGOS_RELEASE_KEY_FINGERPRINT`, porque la clave vive junto al manifiesto en `dist/`) |
| Tabla | `argos.audit_journal` y función `argos.journal_append` (migración `0001_core.sql`) | Diario de auditoría |

## 5. Configuración

Variables con prefijo `ARGOS_`:
- `DATABASE_URL` (obligatoria), `NATS_URL`, `TEMPORAL_ADDRESS`;
- `OIDC_ISSUER` y `OIDC_AUDIENCE`;
- `WORM_STORAGE_PATH`, `LOG_LEVEL`, `LOG_FORMAT_JSON`, `LLM_LOCAL_ENDPOINT`;
- `VAULT_ADDR` y `VAULT_TOKEN`, solo para los servicios que abren conectores; el token se guarda como secreto y no se registra.

En entorno de producción la configuración se rechaza si:
- la base de datos apunta a un host local;
- `WORM_STORAGE_PATH` no es una ruta absoluta;
- el registro no es JSON;
- el emisor OIDC no usa `https`;
- `VAULT_ADDR`, `OPA_URL` o `LLM_LOCAL_ENDPOINT` no usan `https`, o `NATS_URL` no usa `tls://`: por ahí viajan tokens, credenciales y las políticas que deciden veredictos;
- `VAULT_TOKEN` es el token `root` del modo de desarrollo de Vault.

El error nombra el campo, nunca el valor recibido.

Los secretos viven en Vault (kv-v2, montaje `argos`). Cada servicio lee solo su rama `argos/services/<servicio>`, y solo la política del SDK de conectores lee `argos/connectors/<id>`.

## 6. Seguridad y tratamiento de datos

- **Diario encadenado v1** (ADR-0002):
  - cada asiento guarda la marca de tiempo y la carga en forma canónica;
  - su hash es SHA-256 sobre la versión `ARGOS-JOURNAL-v1`, el número de secuencia, los campos con prefijo de longitud y el hash anterior;
  - la secuencia se asigna bajo bloqueo para que las escrituras concurrentes no bifurquen la cadena;
  - los triggers impiden `UPDATE`, `DELETE` y `TRUNCATE`;
  - la canonicalización rechaza números en coma flotante para que el hash no dependa de su representación;
  - una cadena íntegra no prueba por sí sola que no se hayan eliminado los últimos asientos: eso lo cubre el anclaje del hash de cabeza en cada campaña sellada (ARG-066).
- **Secretos:**
  - nunca se escriben en el registro;
  - un secreto inaccesible y uno inexistente producen el mismo error, para no revelar su existencia.
- **Release:**
  - el manifiesto exige imágenes fijadas por digest;
  - se firma con una clave Ed25519 no exportable en Vault Transit;
  - la verificación es posible sin conexión, solo con la clave pública.
- **Decisiones aplicables:** ADR-0001, ADR-0002, ADR-0003 y ADR-0005; notas de desviación ARG-005 y ARG-010.

## 7. Operación

- **Migraciones:** `uv run python tools/migrate.py`. Cada migración deja un asiento en el diario y su suma de control; aplicar una migración ya registrada con otro contenido es un error de integridad.
- **Salud:** `/health/live` indica que el proceso responde; `/health` ejecuta las comprobaciones de dependencias con límite de tiempo.
- **Verificación del diario:** `PostgresJournal(dsn).verify()` devuelve las anomalías con su posición exacta.

## 8. Verificación

- **Tests unitarios** (`libs/common/tests`): configuración, salud, identificadores, diario (con vectores de prueba), registro, migraciones, release y secretos.
- **Tests de integración:** `tests/integration/test_core_migration.py`, `test_journal_pg.py`, `test_vault.py` y `test_release_signing.py`.
- **Prueba de la Fase 1:** 100 asientos escritos y verificados; una corrupción en disco se detecta con su posición y, restaurada, la cadena vuelve a estar íntegra. Manifiesto firmado y verificado (`valid signature`).

## 9. Limitaciones conocidas y pendientes

- `TpmSecretStore` no está implementado: el sellado de secretos en TPM llega con el arranque medido (ARG-082).
- La firma cosign de imágenes espera a un registro interno; hoy las imágenes se fijan por digest local.
- Los registros de acceso de uvicorn aún no salen en JSON (se resuelve con ARG-093).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Configuración, errores, registro, salud, diario v1, migrador, secretos y release firmada | Fase 01 |
| 0.1.0-alpha | 2026-09-15 | `VAULT_ADDR` y `VAULT_TOKEN` para los servicios que abren conectores | Fase 03 (ARG-022) |
| 0.1.0-alpha | 2026-09-18 | En producción, transporte cifrado obligatorio hacia Vault, NATS, OPA y el modelo, y sin token `root` | Auditoría de seguridad (B13) |
| 0.1.0-alpha | 2026-09-18 | Huella de la clave de firma: la clave que acompaña al artefacto solo vale si coincide con la huella fijada | Auditoría de seguridad (B3) |
