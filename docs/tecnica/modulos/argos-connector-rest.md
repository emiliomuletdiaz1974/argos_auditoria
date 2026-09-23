---
id: MOD-argos-connector-rest
kind: module
title: Conector REST declarativo (argos-connector-rest)
module: argos-connector-rest
phases: ["02"]
version: 0.2.0-alpha
commit: 4ed4faf
date: 2026-09-23
status: current
confidentiality: client
---

# Conector REST declarativo (argos-connector-rest)

## 1. Propósito

Lectura de aplicaciones de negocio que exponen una API HTTP. Cada sistema se describe con un **descriptor declarativo**: URL base y lista cerrada de rutas con sus campos de elementos, recuento y paginación. No hace falta programar un conector por aplicación. Implementa ARG-019.

## 2. Alcance y límites

- Solo métodos seguros: `GET`, `HEAD` y `OPTIONS`.
- Solo las rutas declaradas; cualquier otra se rechaza.
- No sigue redirecciones, y la paginación se revalida contra el mismo origen para no salir de la aplicación declarada.

## 3. Arquitectura

- **`RestConnector`:** conector del SDK para sistemas de tipo `api`.
- **`Route.from_descriptor` y `route_for`:** construyen y resuelven la lista cerrada de rutas.
- **`dig()`:** extrae valores por ruta dentro de la respuesta JSON.
- **Resultados:** se registran las cabeceras de seguridad (`SECURITY_HEADERS`) y la versión TLS de la respuesta, útiles para retos de configuración.

Es la base del conector FHIR.

## 4. Interfaces

Sondas del SDK `count`, `sample` y `check_config` sobre las rutas declaradas.

## 5. Configuración

- **Por sistema:** `descriptor` (`base_url`, `routes` con `path`, `items_field`, `count_field`, `page` y `defaults`) y, opcionalmente, `ca_file`, `allow_insecure` y `max_pages` (100 por defecto).
- **Credencial:** token Bearer en Vault.

## 6. Seguridad y tratamiento de datos

**Permisos que necesita la cuenta del cliente:** un token de **solo lectura** limitado a las rutas que se van a consultar.

- Métodos de escritura rechazados por el SDK antes de salir.
- Sin redirecciones.
- **Carga acotada por sonda:** una sonda consume un permiso del presupuesto de carga, así que su paginación también tiene tope: como mucho `max_pages` peticiones, y el recuento sale marcado `capped` si se alcanza.
- Validación TLS con la CA configurada.
- **Solo `https://`:** una URL base `http://` se rechaza al abrir, porque el token Bearer viajaría en claro, salvo que el sistema declare `allow_insecure: true` (en desarrollo, las fuentes en loopback).
- **Cada página cuenta** (SEC-023, F09-22): a partir de la segunda, cada página que elige el servidor se registra en el diario y paga una ficha del presupuesto (`follow_up`).

## 7. Operación

Cada aplicación nueva se incorpora con su descriptor, sin cambios de código.

## 8. Verificación

- **Tests unitarios:** `connectors/rest/tests/test_rest_connector.py`.
- **Test de integración:** `tests/integration/test_rest_keycloak.py`.
- **Evidencia de «sin escrituras»:** el número de usuarios y clientes del realm de la API de prueba no cambia durante la prueba de la Fase 02.

## 9. Limitaciones conocidas y pendientes

Solo admite token Bearer estático desde Vault. El flujo OAuth2 *client credentials* necesita una excepción explícita y revisada (un `POST` al endpoint de tokens) y se incorporará cuando un sistema del cliente lo exija.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-15 | Conector REST declarativo con lista cerrada de rutas y paginación confinada | Fase 02 (ARG-019) |
| 0.1.0-alpha | 2026-09-18 | Transporte cifrado obligatorio: `http://` solo con `allow_insecure: true` declarado | Auditoría de seguridad (M10) |
| 0.1.0-alpha | 2026-09-18 | Tope de páginas por sonda (`max_pages`) | Auditoría de seguridad (M11) |
| 0.2.0-alpha | 2026-09-23 | Páginas siguientes registradas y pagadas | F09-22 |
