---
id: MOD-argos-connector-fhir
kind: module
title: Conector FHIR R4 (argos-connector-fhir)
module: argos-connector-fhir
phases: ["02"]
version: 0.1.0-alpha
commit: d64abd2
date: 2026-09-18
status: current
confidentiality: client
---

# Conector FHIR R4 (argos-connector-fhir)

## 1. Propósito

Lectura de servidores clínicos FHIR R4 para retos de datos de salud y consentimiento: recuentos por tipo de recurso y muestras minimizadas. Implementa la parte FHIR de ARG-020.

## 2. Alcance y límites

- Solo lectura sobre una lista cerrada de recursos sensibles (`SENSITIVE_RESOURCES`: pacientes, diagnósticos, observaciones, entre otros), ampliable por sistema con `extra_resources`.
- Los recuentos usan `_summary=count`, así que no se descargan los recursos para contarlos.

## 3. Arquitectura

- **`FhirConnector`:** extiende el conector REST declarativo y hereda sus garantías (métodos seguros, rutas cerradas y sin redirecciones).
- **Rutas:** se construyen de forma exacta a partir de los tipos de recurso.
- **Datos actuales:** las peticiones llevan `Cache-Control: no-cache`.

## 4. Interfaces

Sondas del SDK `count` y `sample` por tipo de recurso, para sistemas de tipo `clinical.fhir`.

## 5. Configuración

- **Por sistema:** URL base del servidor FHIR, `extra_resources` y `allow_insecure`, opcionales.
- **Credencial:** token Bearer en Vault.

## 6. Seguridad y tratamiento de datos

**Permisos que necesita la cuenta del cliente:** lectura (`read` y `search`) sobre los tipos de recurso configurados; ninguna operación de creación, actualización ni borrado.

Las muestras se minimizan con el hash con clave del SDK.

Como hereda del conector REST, solo acepta `https://` salvo `allow_insecure: true` declarado en el sistema.

## 7. Operación

Un recurso nuevo se incorpora añadiéndolo en `extra_resources` del sistema.

## 8. Verificación

- **Tests unitarios:** `connectors/fhir/tests/test_fhir_connector.py`.
- **Tests de integración:** `tests/integration/test_fhir_source.py` y `test_dev_clinical_sources.py`.
- **Evidencia de «sin escrituras»:** el total del historial (`_history`) del servidor FHIR, consultado sin caché, no cambia durante la prueba de la Fase 02.

## 9. Limitaciones conocidas y pendientes

Las mismas del conector REST respecto a OAuth2.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conector FHIR R4 con recuentos `_summary=count` y rutas de recursos cerradas | Fase 02 (ARG-020) |
| 0.1.0-alpha | 2026-09-18 | Transporte cifrado obligatorio: `http://` solo con `allow_insecure: true` declarado | Auditoría de seguridad (M10) |
