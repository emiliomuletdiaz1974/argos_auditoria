---
id: MOD-argos-auth
kind: module
title: Validación de identidades (argos-auth)
module: argos-auth
phases: ["01"]
version: 0.7.0-alpha
commit: 7cea717
date: 2026-10-08
status: current
confidentiality: client
---

# Validación de identidades (argos-auth)

## 1. Propósito

Validación común de los tokens JWT que emite el realm `argos` de Keycloak y comprobación del rol exigido. Cualquier servicio que expone una API obtiene con esta librería la identidad verificada de quien llama. Implementa ARG-008.

## 2. Alcance y límites

- Valida tokens de usuario emitidos por el realm `argos`.
- No emite tokens ni gestiona usuarios: eso es de Keycloak.
- Todavía no hay cuentas de servicio para llamadas entre servicios (ver §9).

## 3. Arquitectura

- **`JwtValidator`:** descarga y cachea las claves públicas del realm desde su endpoint de certificados (JWKS) y valida cada token.
- **`validate`:** atajo con un validador por defecto construido desde la configuración común.
- **`Identity`:** resultado de la validación (sujeto, nombre y roles) con la propiedad `actor`, que es la que se anota en el diario de auditoría.

Dependencias: `argos-common` (configuración) y PyJWT con soporte criptográfico.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Clase | `JwtValidator(issuer, audience, keys=None)` | Validador con proveedor de claves inyectable |
| Método o función | `validate(token, required_role=None) -> Identity` | Devuelve la identidad o lanza `AuthError` |
| Clase | `Identity(sub, name, roles, amr, sid, full_name)` | Identidad verificada; `actor` para el diario; `has_second_factor` si `amr` trae `otp` (F09-07) |
| Constante | `ROLES` | `platform_admin`, `campaign_manager`, `dpo_reviewer`, `read_only_auditor` |
| Realm | `argos` en Keycloak | Clientes `argos-console` y `argos-api` |

## 5. Configuración

`ARGOS_OIDC_ISSUER` (URL del realm; `https` obligatorio en producción) y `ARGOS_OIDC_AUDIENCE`. Con `ARGOS_OIDC_INTERNAL_URL` (K-08), las claves se piden a esa dirección interna del realm y el token tiene que seguir llevando `ARGOS_OIDC_ISSUER`: es lo que hace falta cuando Keycloak se publica con un nombre que el servicio no alcanza desde dentro. `JwtValidator(issuer, audience, realm_url=…)`.

## 6. Seguridad y tratamiento de datos

- **Tokens en sus bordes (QA-009):** 30 s de margen de reloj (`LEEWAY_SECONDS`); `realm_access` o `roles` con otra forma dan un conjunto de roles vacío, no un 500 ni los caracteres de una cadena.
- **Nombre completo** (2026-10-08): `Identity.full_name` es el claim `name` del token (ámbito `profile`), vacío si la cuenta no lo tiene. Solo sirve para lo que lee una persona, como el expediente impreso; quién es la persona lo dice siempre `sub` (`actor`).
- **Sesión del token** (F09-32): `Identity.sid` es la sesión del realm a la que pertenece el token (claim `sid`). La API la usa para rechazar los tokens de una sesión cerrada antes de que caduquen.
- **Segundo factor** (F09-07, DP-14):
  - `platform_admin` y `dpo_reviewer` heredan el rol `mfa_required`, y el flujo de navegador del realm (`argos browser`) les pide TOTP después de la contraseña. Si aún no lo tienen, se lo hace configurar.
  - Política TOTP: HMAC-SHA-256, 6 dígitos, 30 s, sin reutilizar un código.
  - El token lleva `amr` (RFC 8176) con `pwd` y `otp`, gracias a las referencias de cada autenticador y al mapper `amr`. `Identity.amr` lo recoge. Cada referencia lleva `default.reference.maxAge` de 36 000 s, la vida máxima de la sesión. Sin ese valor, Keycloak solo la incluye en el mismo instante en que se ganó: un token renovado o una sesión SSO reutilizada salían con `amr` vacío.
  - Contraseñas: longitud mínima 12, historial de 5, ni el usuario ni el correo.
  - Bloqueo temporal tras 5 fallos (de 60 s a 15 min).
  - En desarrollo, `dpo.test` tiene un secreto TOTP sembrado (`dev-only-…`) que solo existe en el realm de desarrollo. Lo comprueba `tests/integration/test_keycloak_mfa.py`.
- **Algoritmo:** solo `RS256`; se rechaza cualquier otro.
- **Claims obligatorios:** `exp`, `iat`, `iss`, `aud` y `sub`; se comprueban emisor y audiencia.
- **Roles:** se leen de `realm_access.roles`. Pedir un rol que no está en la lista cerrada es un error de programación y se rechaza.
- **Errores:** los mensajes solo indican el tipo de fallo, nunca el contenido del token.

## 7. Operación

- Keycloak en desarrollo: `127.0.0.1:8180` (nota de desviación ARG-002-003).
- Las claves públicas del realm se descargan de su endpoint de certificados y se mantienen en caché. El comportamiento ante una rotación de claves no tiene todavía prueba propia.

## 8. Verificación

- **Tests unitarios:** `libs/auth/tests/test_validate.py` (firma, emisor, audiencia, caducidad, roles y algoritmo).
- **Test de integración:** `tests/integration/test_keycloak.py` (tokens reales del realm de desarrollo).

## 9. Limitaciones conocidas y pendientes

- La variante `validate()` que lee la configuración global no tiene test propio (pendiente para la Fase 08).
- El realm no tiene clientes con cuentas de servicio, así que las llamadas entre servicios con token llegan en las Fases 05 y 08.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-14 | Realm con cuatro roles y validación común de JWT | Fase 01 (ARG-008) |
| 0.2.0-alpha | 2026-09-23 | `amr` en la identidad y segundo factor TOTP en el realm para los roles que deciden | F09-07 (ARG-072) |
| 0.3.0-alpha | 2026-09-24 | `Identity.sid`: la sesión del realm del token | F09-32 (SEC-060) |
| 0.4.0-alpha | 2026-09-28 | Margen de reloj y roles del realm con forma inesperada | QA-34 (QA-009) |
| 0.5.0-alpha | 2026-09-30 | El realm conserva `amr` en los tokens renovados y en la SSO (`default.reference.maxAge`) | F09-07 (ARG-072) |
| 0.6.0-alpha | 2026-10-05 | `JwtValidator(realm_url=)`: claves del realm por su dirección interna, con el emisor público | K-08 |
| 0.7.0-alpha | 2026-10-08 | `Identity.full_name` desde el claim `name`, para el expediente impreso | petición directa |
