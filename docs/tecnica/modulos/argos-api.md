---
id: MOD-argos-api
kind: module
title: API única autenticada v1 (argos-api)
module: argos-api
phases: ["08"]
version: 0.1.0-alpha
commit: de46a2e
date: 2026-09-20
status: current
confidentiality: client
---

# API única autenticada v1 (argos-api)

## 1. Propósito

Es la única puerta autenticada a ARGOS: sistemas, inventario, campañas, hallazgos, evidencia, credenciales, asistente, aprobaciones y suscripciones. No hay rutas reservadas a la consola; lo que hace la consola lo puede hacer la integración del cliente con el mismo contrato y la misma autorización. Implementa ARG-071 (pliego P-18, P-19, P-20) y aplica el ADR-0012.

## 2. Alcance y límites

- **Hace:** publicar el contrato de la v1, resolver las peticiones llamando a las librerías del dominio y dejar asiento en el diario de toda mutación (esto último, desde F08-03).
- **No hace:** no escribe SQL sobre tablas de otras fases; no expone material público (eso es `evidence-api` y el comprobador, que siguen siendo servicios aparte).
- **En esta tarea (F08-01)** solo existe el esqueleto: todas las rutas están declaradas y validan sus parámetros, pero devuelven `501` hasta que su tarea las implemente.

## 3. Arquitectura

- `argos_api.app.create_app(validator)`: monta `/health`, los routers de cada recurso bajo `/api/v1` y los manejadores de error; expone el contrato en `/api/v1/openapi.json`.
- `argos_api.routers.*`: un módulo por recurso (`systems`, `inventory`, `campaigns`, `findings`, `evidence`, `credentials`, `assistant`, `approvals`, `webhooks`, `session`).
- `argos_api.http`: lo que comparten todos los recursos —el problema RFC 9457, la paginación por cursor y la cabecera de idempotencia—, para que ningún router lo repita.
- `argos_api.auth`: exige un token del realm `argos` con algún rol de ARGOS. La matriz de permisos por ruta llega en F08-02.
- El contrato **se genera del código**: `tools/api_contract.py` lo escribe en `services/api/openapi.json` y `--check` falla si divergen. `make api-contract` está en `make check` y en el CI.

### Decisiones transversales

| Decisión | Cómo se materializa |
|---|---|
| Versión en la ruta | Todo cuelga de `/api/v1`; solo `/health` queda fuera |
| Errores | `application/problem+json` (RFC 9457) en **todos** los códigos ≥ 400, incluido el 404 de una ruta inexistente |
| Paginación | `cursor` opaco y `limit` (1…200, por defecto 50); nunca `offset` |
| Idempotencia | `Idempotency-Key` en los POST que crean (campañas, credenciales, suscripciones) |
| Autenticación | `Bearer` del Keycloak del appliance; sin token, `401` con `WWW-Authenticate` |

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Función pública | `app.create_app(validator=None) -> FastAPI` | La aplicación; sin validador, toda ruta autenticada responde `401` |
| Contrato | `services/api/openapi.json` | OpenAPI 3.1 de la v1, versionado y comprobado en CI |
| Herramienta | `tools/api_contract.py [--check]` | Genera el contrato o comprueba que el fichero está al día |
| Rutas | `/api/v1/{systems,inventory,campaigns,findings,evidence,credentials,assistant,approvals,webhooks,auth}` | 32 operaciones declaradas; ver el contrato |
| Salud | `GET /health` | Sin token |

## 5. Configuración

Por ahora, el emisor y la audiencia OIDC que recibe el validador (`ARGOS_OIDC_ISSUER`, `ARGOS_OIDC_AUDIENCE`, ya existentes). El contenedor y su punto de entrada llegan con F08-16.

## 6. Seguridad y tratamiento de datos

- Ninguna ruta autenticada se resuelve sin un token válido con rol del realm; la separación de funciones por ruta es F08-02.
- Los cuerpos se validan con Pydantic y un cuerpo inválido sale como `422` en formato problema, sin filtrar trazas.
- Decisiones aplicables: ADR-0012 (API única), ADR-0013 (consola), nota de desviación ARG-071-080 (identificadores en inglés y sin `INSERT` propios).

## 7. Operación

En desarrollo, `uv run uvicorn argos_api.app:create_app --factory`. El servicio del `compose` y la consola servida como estáticos llegan en F08-16.

## 8. Verificación

- `tests/contract/test_api_v1.py`: cada recurso declarado, la forma del error, la paginación por cursor, la cabecera de idempotencia, el `401` anónimo y que el fichero versionado es exactamente el generado.
- `make api-contract`, dentro de `make check` y del CI.

## 9. Limitaciones conocidas y pendientes

- Las rutas responden `501` hasta su tarea (F08-04 en adelante); `challenge-api` sigue en pie hasta F08-15.
- El montaje de GraphQL bajo `/api/v1/inventory/graph` (ADR-0012 §5) llega con el inventario, en F08-05.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-20 | Contrato OpenAPI v1, esqueleto de rutas y suite de contrato | F08-01 |
