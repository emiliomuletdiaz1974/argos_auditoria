---
id: FASE-02
kind: phase
title: Fase 02 · Conectores de solo lectura
phase: "02"
version: 0.1.0-alpha
commit: bba9ed6
date: 2026-09-15
status: current
confidentiality: client
---

# Fase 02 · Conectores de solo lectura

## 1. Resumen

La Fase 02 da a ARGOS acceso a los sistemas del cliente con una garantía verificable: **ARGOS solo lee**. Todos los conectores comparten un contrato que:
- valida cada consulta como de solo lectura;
- la anota en un diario auditable antes de ejecutarla;
- limita la carga sobre el sistema con ventanas horarias, tasas y un cortacircuitos.

## 2. Alcance

- **Componentes incluidos:** ARG-011 a ARG-020.
- **Tipos de fuente cubiertos:**
  - bases de datos: PostgreSQL, MariaDB, Oracle y SQL Server;
  - ficheros: SMB, NFS y S3;
  - directorio: LDAP y Active Directory;
  - APIs REST;
  - FHIR R4;
  - DICOM.
- **Fuera de la fase:**
  - el conector de registros (logs), aplazado hasta que exista;
  - el flujo OAuth2 *client credentials*, que se incorporará cuando un sistema lo exija.

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| SDK de conectores | [`modulos/argos-connector-sdk.md`](../modulos/argos-connector-sdk.md) | 0.1.0-alpha |
| Bases de datos | [`modulos/argos-connector-sql.md`](../modulos/argos-connector-sql.md) | 0.1.0-alpha |
| Ficheros | [`modulos/argos-connector-files.md`](../modulos/argos-connector-files.md) | 0.1.0-alpha |
| Directorio | [`modulos/argos-connector-ldap.md`](../modulos/argos-connector-ldap.md) | 0.1.0-alpha |
| REST | [`modulos/argos-connector-rest.md`](../modulos/argos-connector-rest.md) | 0.1.0-alpha |
| FHIR | [`modulos/argos-connector-fhir.md`](../modulos/argos-connector-fhir.md) | 0.1.0-alpha |
| DICOM | [`modulos/argos-connector-dicom.md`](../modulos/argos-connector-dicom.md) | 0.1.0-alpha |

Además:
- la migración `0002_connectors.sql` (diario previo de consultas);
- un entorno simulado con once fuentes sintéticas y cuentas de solo lectura.

## 4. Prueba de la fase

**Criterio del Plan Director:** descubrir y muestrear cada tipo de fuente con evidencia, en el propio servidor, de que no hubo ninguna escritura, y con cada consulta anotada en el diario antes de ejecutarse.

**Ejecución (2026-09-15):**
- entorno simulado limpio, con datos sintéticos;
- test `tests/e2e/test_phase2_acceptance.py` sobre seis tipos de fuente: PostgreSQL y MariaDB, SMB y S3, LDAPS, API REST, FHIR y DICOM.

**Resultado: aprobada a la primera.** La evidencia de servidor es idéntica antes y después:

| Fuente | Evidencia |
|---|---|
| PostgreSQL | `log_statement=all` sin escrituras de la cuenta de ARGOS |
| MariaDB | Registro general sin escrituras de la cuenta de ARGOS |
| LDAP | Ninguna entrada modificada ni creada |
| SMB y S3 | Manifiesto de sumas de control idéntico |
| FHIR | Total de `_history` sin cambios |
| DICOM | Contadores de estadísticas sin cambios |
| API REST | Mismos usuarios y clientes |

Para confirmar que esa evidencia no es vacía:
- en 30 minutos se registraron 400 sentencias de ARGOS en PostgreSQL y 131 en MariaDB;
- un `INSERT` deliberado de prueba sí quedó detectado.

En el diario, cada sonda tiene su asiento previo, no hay consultas abiertas y la cadena está íntegra.

## 5. Decisiones y desviaciones

Notas de desviación ARG-011, ARG-012, ARG-013, ARG-014-016, ARG-017, ARG-018 y ARG-019-020. En resumen:
- contrato de ejecución final e inevitable;
- diario previo con cierre único de cada consulta;
- presupuesto de carga con cortacircuitos por latencia;
- sesiones de solo lectura por motor de base de datos;
- REST declarativo con rutas cerradas y sin redirecciones;
- DICOM limitado a C-ECHO y C-FIND.

## 6. Interfaces que exporta

Tabla completa en `docs/fases/interfaces-F02.md`. La Fase 03 (inventario), la Fase 05 (sondas de campaña) y la Fase 07 (evidencia enlazada al diario de consultas) consumen el contrato de conector, los tipos de sonda, el diario previo y el presupuesto de carga.

## 7. Pendientes al cierre

- **Prueba contra un entorno real** del cliente: pendiente de acceso de red y de cuentas de solo lectura por tipo de fuente.
- **Integración real con Oracle y SQL Server:** pendiente de una máquina con unos 6 GB de RAM libres.
- **Presupuesto de carga compartido** entre réplicas: Fase 10.

## 8. Identificación del cierre

Tag `fase-02`, commit `bba9ed6`, 2026-09-15.
