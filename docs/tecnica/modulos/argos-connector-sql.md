---
id: MOD-argos-connector-sql
kind: module
title: Conectores de bases de datos (argos-connector-sql)
module: argos-connector-sql
phases: ["02", "03"]
version: 0.3.0-alpha
commit: 4ed4faf
date: 2026-09-23
status: current
confidentiality: client
---

# Conectores de bases de datos (argos-connector-sql)

## 1. Propósito

Lectura de catálogo, recuentos, muestras minimizadas y comprobaciones de configuración en bases de datos relacionales del cliente. Implementa:
- ARG-014: SQL genérico sobre SQLAlchemy;
- ARG-015: PostgreSQL con catálogo profundo;
- ARG-016: Oracle y SQL Server.

## 2. Alcance y límites

- Solo lectura: nunca crea, modifica ni borra datos ni estructuras.
- No extrae valores de negocio en claro. Las muestras salen como hashes con clave y como tasas de validación de identificadores; la validación en origen se añadió en la Fase 03.

## 3. Arquitectura

| Clase | Tipo de sistema | Particularidades |
|---|---|---|
| `SqlConnector` | `rdbms` | Sesión de solo lectura por dialecto en cada conexión del pool; sentencias compiladas y registradas literalmente; comprobaciones de configuración por nombre (`CONFIG_CHECKS`) |
| `PostgresConnector` | `rdbms.postgresql` | Catálogo con tamaño, filas estimadas, comentarios y réplica; comprobaciones `privileges` (incluidos roles sin login), `encryption_at_rest` y `replica_status` |
| `OracleConnector` | `rdbms.oracle` | Catálogo nativo; `audit_status`, `generic_accounts` y `privileged_grants`; excluye esquemas del sistema |
| `MssqlConnector` | `rdbms.mssql` | Catálogo nativo; mismas comprobaciones de auditoría y privilegios |

**Sesión de solo lectura por motor:**

| Motor | Mecanismo |
|---|---|
| PostgreSQL | `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` y límite de tiempo por sentencia |
| MariaDB y MySQL | `SET SESSION TRANSACTION READ ONLY` y límite de tiempo de ejecución |
| Oracle | `SET TRANSACTION READ ONLY` en cada transacción |
| SQL Server | Nivel de aislamiento configurable por sistema (instantánea) |

## 4. Interfaces

Sondas `scan_schema`, `count`, `sample` (con `validators`) y `check_config`, a través de `Connector.execute` del SDK.

`count` acepta además `params.filters`: una lista de `{column, operator, value, cast}` con la que un reto compara el nodo para el que se compiló. El nombre de la columna no puede viajar como parámetro de una sentencia, así que se valida como identificador; el valor siempre viaja enlazado, y el `cast` (hoy solo `text`) se declara, nunca se adivina, porque buscar un identificador en todas las columnas de una tabla se topa con columnas de otro tipo y un choque de tipos no es un hallazgo.

## 5. Configuración

- **Por sistema:** `statement_timeout_ms`, y opcionalmente `isolation_level` (SQL Server), `mrn_pattern` (patrón del número de historia clínica) y `allow_insecure`.
- **Transporte:** la URL tiene que pedir TLS **verificado**: `sslmode=verify-ca` o `verify-full` en PostgreSQL, `ssl_ca` en MySQL y MariaDB, `Encrypt=yes` en SQL Server y `protocol=tcps` en Oracle. `sslmode=require` no basta, porque cifra sin comprobar quién responde. Sin eso el conector no abre, salvo `allow_insecure: true` declarado en el sistema.
- **Credenciales:** en Vault, `argos/connectors/<id>`.

## 6. Seguridad y tratamiento de datos

**Permisos que necesita la cuenta del cliente** (comprobados en los scripts del entorno simulado):

| Motor | Permisos |
|---|---|
| PostgreSQL | `LOGIN`, `CONNECT` a la base, `USAGE` en el esquema y `SELECT` en sus tablas; recomendado `default_transaction_read_only = on` para el rol |
| MariaDB y MySQL | `SELECT` sobre la base a inventariar |
| Oracle | `CREATE SESSION`, `SELECT` en las tablas, `SELECT_CATALOG_ROLE` y `AUDIT_VIEWER` para las comprobaciones de auditoría |
| SQL Server | Pertenencia a `db_datareader`, `VIEW SERVER STATE` y `VIEW ANY DEFINITION` |

Ninguno necesita DDL ni DML. Además:
- toda sentencia pasa por la validación de solo lectura y el diario previo del SDK;
- los validadores desconocidos se rechazan antes de anotar la consulta.
- **Tiempo máximo también en SQL Server** (SEC-006, F09-21): `driver_options` pasa `statement_timeout_ms` a `pymssql` al conectar (`timeout` y `login_timeout`, en segundos). Antes esperaba sin límite.
- **Exploración en una sola sentencia registrada** (SEC-023, F09-22): `scan_schema` ejecuta una sentencia literal sobre `information_schema` (`COLUMNS_SQL`; en PostgreSQL, `CATALOG_SQL` con tamaños y columnas en una consulta) que se valida, se registra en el diario y paga su ficha. Ya no se usa el inspector de SQLAlchemy, que lanzaba una consulta por esquema y por tabla sin diario ni presupuesto; queda solo para SQLite, que no es un motor de cliente. El tipo de columna es el del catálogo en mayúsculas, con su longitud.

## 7. Operación

Una sentencia lenta queda cortada por el límite de tiempo configurado, y la latencia alimenta el cortacircuitos del presupuesto de carga.

## 8. Verificación

- **Tests unitarios** (`connectors/sql/tests`): genérico, PostgreSQL, Oracle y SQL Server, y validación.
- **Tests de integración:** `test_sql_sources.py`, `test_postgres_catalog.py`, `test_sql_validators.py` y `test_oracle_mssql_sources.py` (perfil pesado).
- **Evidencia de «sin escrituras»:**
  - en PostgreSQL, `log_statement=all` no registró escrituras de la cuenta de ARGOS;
  - en MariaDB, el registro general tampoco; un `INSERT` deliberado de prueba fue rechazado por el servidor y sí quedó detectado.

## 9. Limitaciones conocidas y pendientes

La integración real con Oracle y SQL Server está escrita pero **no se ha ejecutado todavía**: necesita unos 6 GB de RAM libres para el perfil pesado.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conectores SQL genérico, PostgreSQL, Oracle y SQL Server | Fase 02 (ARG-014…016) |
| 0.1.0-alpha | 2026-09-15 | Validación de identificadores en origen en las muestras | Fase 03 (ARG-024) |
| 0.1.0-alpha | 2026-09-17 | Filtros declarados en la sonda `count`, con la columna validada y el valor enlazado | Fase 05 (F05-99) |
| 0.1.0-alpha | 2026-09-18 | TLS verificado obligatorio por dialecto salvo `allow_insecure` declarado | Auditoría de seguridad (M10) |
| 0.2.0-alpha | 2026-09-23 | `driver_options`: tiempo máximo de sentencia en `pymssql` | F09-21 |
| 0.3.0-alpha | 2026-09-23 | Exploración con `COLUMNS_SQL` y `CATALOG_SQL` literales en lugar del inspector | F09-22 |
