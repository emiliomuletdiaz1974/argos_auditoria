---
id: MOD-argos-connector-files
kind: module
title: Conector de ficheros SMB, NFS y S3 (argos-connector-files)
module: argos-connector-files
phases: ["02"]
version: 0.2.0-alpha
commit: b432f8a
date: 2026-09-23
status: current
confidentiality: client
---

# Conector de ficheros SMB, NFS y S3 (argos-connector-files)

## 1. Propósito

Inventario de repositorios de ficheros del cliente: recorrido de metadatos (rutas, tamaños, fechas, permisos) y detección del tipo real de fichero por sus primeros bytes. Implementa ARG-017.

## 2. Alcance y límites

- Lee metadatos y, como mucho, los **primeros 4096 bytes** de un fichero para identificar su tipo (por ejemplo, la marca DICOM en el desplazamiento 128).
- Nunca lee contenidos completos, ni escribe, mueve, renombra o borra ficheros.

## 3. Arquitectura

- **`FilesConnector`:** conector del SDK para sistemas de tipo `files`.
- **Motores intercambiables (`FileBackend`):**
  - `local`: montajes NFS o locales;
  - `smb`: recursos compartidos Windows;
  - `s3`: almacenamiento compatible con S3.
- **Operaciones del motor:** `walk` (recorrido), `read_head` (cabecera del fichero), `get_acl` (permisos) y `close`.
- **`sniff()`:** identifica el formato por la cabecera, no por la extensión.

## 4. Interfaces

Sondas del SDK sobre metadatos: `scan_schema`, `count` y `sample`, esta con cabeceras minimizadas.

## 5. Configuración

- **Por sistema:** `protocol` (`local`, `smb` o `s3`), `mount` (solo `local`), `max_walk_entries` (tope del recorrido) y `allow_insecure`.
- **Transporte:** SMB exige cifrado SMB 3 y S3 solo acepta un `endpoint_url` `https://`, porque el primer bloque de cada fichero cruza la red antes de convertirse en hash. `allow_insecure: true` en el sistema deja SMB a lo que negocie el servidor y acepta S3 por `http://`.
- **Credenciales:** en Vault.

## 6. Seguridad y tratamiento de datos

**Permisos que necesita la cuenta del cliente:**

| Protocolo | Permisos |
|---|---|
| SMB | Lectura del recurso compartido y de sus ACL |
| NFS o local | Montaje de solo lectura |
| S3 | Listar el bucket y leer objetos (`ListBucket` y `GetObject`); ningún permiso de escritura |

- La lectura se limita a 4096 bytes por fichero.
- El recorrido está acotado por `max_walk_entries` y por el presupuesto de carga del SDK.
- **Recorrido SMB acotado** (SEC-053, F09-22): los directorios listados cuentan contra el tope igual que los ficheros, y los enlaces simbólicos se listan pero no se siguen.

## 7. Operación

En árboles muy grandes, el recorrido se detiene al alcanzar `max_walk_entries` (por defecto, 1 000 000 entradas) y el resultado lo marca con `capped`.

## 8. Verificación

- **Tests unitarios:** `connectors/files/tests/test_files_connector.py`.
- **Tests de integración:** `test_files_sources.py` y `test_dev_file_sources.py`.
- **Evidencia de «sin escrituras»:** el manifiesto de sumas de control del árbol SMB y del bucket S3 es idéntico antes y después de la prueba de la Fase 02.

## 9. Limitaciones conocidas y pendientes

Ninguna específica del conector.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conector de ficheros con recorrido de metadatos y muestras minimizadas | Fase 02 (ARG-017) |
| 0.1.0-alpha | 2026-09-18 | Cifrado SMB 3 exigido y S3 solo por `https://`, salvo `allow_insecure` declarado | Auditoría de seguridad (M10) |
| 0.2.0-alpha | 2026-09-23 | Recorrido SMB con directorios contados y sin seguir enlaces | F09-22 |
