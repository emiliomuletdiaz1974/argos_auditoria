---
id: MOD-argos-connector-dicom
kind: module
title: Conector DICOM (argos-connector-dicom)
module: argos-connector-dicom
phases: ["02"]
version: 0.2.0-alpha
commit: 4ed4faf
date: 2026-09-23
status: current
confidentiality: client
---

# Conector DICOM (argos-connector-dicom)

## 1. Propósito

Consulta de archivos de imagen médica (PACS) para retos de imagen: comprueba la conectividad y cuenta y muestrea estudios con consultas de búsqueda. Implementa la parte DICOM de ARG-020.

## 2. Alcance y límites

- Solo usa dos servicios DICOM:
  - **Verification** (C-ECHO), para comprobar la conectividad;
  - **Study Root Find** (C-FIND), para consultar estudios.
- Nunca recupera imágenes (sin C-MOVE ni C-GET) ni almacena (sin C-STORE).

## 3. Arquitectura

- **`DicomConnector`:** conector del SDK para sistemas de tipo `clinical.dicom`.
- **Negociación cerrada:** solo propone los contextos de presentación permitidos (`REQUESTED_CONTEXTS`, `ALLOWED_ABSTRACT_SYNTAXES`).
- **Tope de estudios:** las búsquedas se cortan en `max_studies`. Si se alcanza, la asociación se **aborta** en lugar de liberarse, para no dejar respuestas pendientes en el PACS, y el resultado lo indica con `capped`.

## 4. Interfaces

Sondas del SDK `count` y `sample` sobre estudios.

## 5. Configuración

**Por sistema:** `ae_title` (título de aplicación de ARGOS), `timeout_s` y `max_studies` (por defecto, 100 000).

## 6. Seguridad y tratamiento de datos

**Permisos que necesita en el PACS del cliente:** un AE Title para ARGOS (por ejemplo `ARGOS_QR`) con permiso **solo de consulta** (C-ECHO y C-FIND); sin C-MOVE, C-GET ni C-STORE.

Las muestras de atributos de estudio se minimizan con el hash con clave del SDK.
- **La apertura también cuenta** (SEC-023, F09-22): la asociación y el C-ECHO de `open()` se registran en el diario (`check_config` sobre `association`) y pagan su ficha.

## 7. Operación

- Una asociación rechazada, abortada o sin respuesta se informa como error de conexión.
- La latencia alimenta el cortacircuitos del presupuesto de carga.

## 8. Verificación

- **Tests unitarios:** `connectors/dicom/tests/test_dicom_connector.py`.
- **Tests de integración:** `tests/integration/test_dicom_source.py` y `test_dev_clinical_sources.py`.
- **Evidencia de «sin escrituras»:** los contadores de estadísticas del PACS de prueba no cambian durante la prueba de la Fase 02.

## 9. Limitaciones conocidas y pendientes

Ninguna específica del conector.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conector DICOM limitado a C-ECHO y C-FIND con muestras minimizadas | Fase 02 (ARG-020) |
| 0.2.0-alpha | 2026-09-23 | Asociación y C-ECHO de la apertura registrados y pagados | F09-22 |
