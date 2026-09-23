---
id: MOD-argos-connector-sdk
kind: module
title: SDK de conectores de solo lectura (argos-connector-sdk)
module: argos-connector-sdk
phases: ["02", "03"]
version: 0.2.0-alpha
commit: 031b9bc
date: 2026-09-23
status: current
confidentiality: client
---

# SDK de conectores de solo lectura (argos-connector-sdk)

## 1. Propósito

Contrato común de todos los conectores con los sistemas del cliente. Garantiza por construcción tres principios:
- **solo lectura**;
- **toda consulta queda anotada antes de ejecutarse**;
- **la carga sobre el sistema del cliente está acotada**.

Implementa ARG-011 (contrato y arnés de escritura), ARG-012 (diario previo de consultas) y ARG-013 (presupuesto de carga y cortacircuitos). Desde la Fase 03 incluye también los validadores de identificadores españoles (ARG-024).

## 2. Alcance y límites

- Define cómo se ejecuta una sonda; no conecta por sí mismo con ningún sistema, eso lo hacen los conectores concretos.
- Ninguna vía de escritura está disponible:
  - las sentencias SQL se validan como de solo lectura antes de ejecutarse;
  - los métodos HTTP se limitan a los seguros;
  - un conector sin superficie de escritura verificable no pasa sus tests.

## 3. Arquitectura

Toda sonda pasa por `Connector.execute`, que es final y no puede saltarse. Recorre siempre este orden:

1. **Renderizar** la sonda en la sentencia o petición concreta del conector.
2. **Validar** que es de solo lectura (`validate_read_only_sql` o `assert_safe_http_method`). Si no lo es, se registra el rechazo y no se ejecuta.
3. **Anotar en el diario** la consulta como `emitted`, con asiento `query.emit` en el diario de auditoría.
4. **Consumir presupuesto:** ventana horaria permitida, tasa de consultas y límite de filas; si el cortacircuitos está abierto, no se ejecuta.
5. **Ejecutar** y cerrar la fila del diario como `completed` o `failed`.

Otras piezas:
- **Datos de muestra:** se minimizan con un hash HMAC-SHA256 con clave (`ValueHasher`), de modo que ningún valor en claro sale del sistema de origen.
- **Credenciales:** se leen de Vault en `argos/connectors/<id>`.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Clase | `Connector(system_id, config, context)` | Base de conectores; `execute(ProbeSpec) -> ProbeResult` |
| Clases | `ProbeSpec(kind, target, statement, params)`, `ProbeResult(...)` | Tipos de sonda `scan_schema`, `count`, `sample`, `check_config` |
| Clase | `ConnectorContext(journal, budget, hasher, credentials)` | Dependencias inyectadas en cada conector |
| Clase | `QueryJournal(dsn, system_id)` | Diario previo; actor `system:connector:<id>`, asientos `query.emit` y `query.reject` |
| Clase | `LoadBudget(system_id, config, ...)` | Ventanas por día y zona horaria, tasa por minuto con ráfaga, filas máximas por sonda y cortacircuitos por latencia |
| Función | `bus_circuit_listener(bus, loop)` | Publica `campaign.circuit_open.v1` al abrirse un cortacircuitos |
| Funciones | `validate_read_only_sql`, `assert_safe_http_method` | Validación de solo lectura |
| Función | `require_tls(encrypted, config, target)` | Rechaza al abrir un transporte sin cifrar salvo que el sistema declare `allow_insecure: true` |
| Funciones | `is_valid_dni`, `is_valid_nie`, `is_valid_nuss`, `is_valid_iban_es`, `mrn_validator`, `acceptance_rates` | Validadores con dígito de control (Fase 03) |
| Tabla | `argos.connector_queries` (migración `0002_connectors.sql`) | Estados `emitted`, `completed`, `failed`, `rejected`; un trigger impide borrar filas y modificar las cerradas |
| Arnés | `argos_connector.testing` | `assert_no_write_surface`, `assert_sql_writes_rejected`, `assert_http_writes_rejected` para los tests de cualquier conector |

## 5. Configuración

- **Por sistema, en la configuración de su conector:** ventanas de trabajo por día y zona horaria, tasa y ráfaga de consultas, filas máximas por sonda y umbral de latencia del cortacircuitos.
- **Valores por defecto:** 30 consultas por minuto, ráfaga de 10, ventana de todo el día, 10 000 filas por sonda y apertura del cortacircuitos cuando la mediana de latencia supera 2000 ms.
- **Credenciales:** en Vault; solo la política del SDK de conectores puede leer `argos/connectors/*`.

## 6. Seguridad y tratamiento de datos

- **Solo lectura en dos capas:** validación en ARGOS y cuenta de solo lectura en el sistema del cliente (ver los permisos en cada documento de conector).
- **Funciones con efectos:** la validación rechaza, además de las sentencias de escritura, las funciones que ejecutan sentencias en otra sesión o en otro servidor (`dblink`, `OPENQUERY`, `OPENROWSET`, `query_to_xml`), salen a la red o al sistema de ficheros (`UTL_*`, `xp_*`, `pg_read*`, `pg_stat_file`, `lo_*`) o toman bloqueos (`pg_advisory*`, `get_lock`). El nombre se comprueba con su paquete (`utl_http.request`), y cualquier argumento de texto que sea una sentencia de escritura también se rechaza.
- **Transparencia:** cada consulta queda en `argos.connector_queries` y en el diario encadenado antes de ejecutarse; las rechazadas también quedan anotadas.
- **Minimización:** las muestras solo salen como hashes con clave y como tasas agregadas de validación, nunca como valores.
- **Carga:** fuera de ventana o con el cortacircuitos abierto la sonda no se ejecuta, y el evento permite reprogramar la campaña.
- **Decisiones aplicables:** notas de desviación ARG-011, ARG-012 y ARG-013.
- **Validación alineada con el motor** (SEC-005, SEC-006 y SEC-021, F09-21):
  - se rechazan los comentarios que un motor ejecuta (`/*!`, `/*M!`, `/*+`, `--` sin espacio);
  - se rechazan las pistas de tabla y de consulta;
  - la lista de denegadas se compara con cada segmento del nombre cualificado;
  - una función que sqlglot no modela pasa solo si está en `ALLOWED_ANONYMOUS` y es de un esquema de catálogo.
  - Las evasiones forman parte de `SQL_WRITE_ATTEMPTS`, que recorren el test puro en los cinco dialectos y la integración contra las fuentes reales.

## 7. Operación

- El estado de cada consulta se puede auditar en `argos.connector_queries`.
- La apertura de un cortacircuitos genera el evento `campaign.circuit_open.v1`.

## 8. Verificación

- **Tests unitarios** (`connectors/sdk/tests`): contrato base, presupuesto, hash del diario, minimización, solo lectura y validadores.
- **Tests de integración:** `tests/integration/test_query_journal_pg.py` y `test_budget_circuit_event.py`.
- **Prueba de la Fase 02:** cada sonda contra seis tipos de fuente tuvo su asiento `query.emit` previo, sin filas abiertas y con la cadena del diario íntegra.

## 9. Limitaciones conocidas y pendientes

El presupuesto de carga vive en la memoria de cada proceso; con varias réplicas por sistema habrá que compartirlo (Fase 10).

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Contrato de solo lectura, arnés de escritura, diario previo y presupuesto de carga | Fase 02 (ARG-011…013) |
| 0.1.0-alpha | 2026-09-15 | Validadores de DNI, NIE, NUSS, IBAN y NHC | Fase 03 (ARG-024) |
| 0.1.0-alpha | 2026-09-18 | La validación de solo lectura rechaza funciones con efectos por familia y paquete, y sentencias de escritura pasadas como texto | Auditoría de seguridad (A1) |
| 0.1.0-alpha | 2026-09-18 | `require_tls`: transporte cifrado obligatorio salvo declaración explícita en el sistema | Auditoría de seguridad (M10) |
| 0.2.0-alpha | 2026-09-23 | Sin comentarios ejecutables ni pistas, lista de denegadas por segmento y funciones no modeladas solo desde `ALLOWED_ANONYMOUS` | F09-21 |
