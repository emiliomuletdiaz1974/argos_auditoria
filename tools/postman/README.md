# Colección de Postman de la API v1

`ARGOS-API-v1.postman_collection.json` recorre las 54 operaciones del contrato `services/api/openapi.json` en 68 peticiones organizadas en 14 carpetas. Sirve para probar a mano la API en el **entorno de desarrollo** (`make dev`).

## Uso

1. Levanta el entorno: `make dev`. Si faltan las fuentes simuladas: `uv run --env-file .env.example python tools/register_dev_sources.py`.
2. Importa el archivo en la aplicación de escritorio de Postman. El navegador no deja cambiar la cabecera `Host` que necesitan los tokens.
3. Ejecuta **00 · Preparación y tokens → Salud de la API** y después las carpetas en orden.

## Autenticación

Cada petición declara su rol (`{{token_manager}}`, `{{token_dpo}}`, `{{token_admin}}` o `{{token_auditor}}`) y el script de la colección pide el token a Keycloak con el cliente `argos-tests`, con `Host: keycloak:8080` para que el emisor coincida con `ARGOS_OIDC_ISSUER`. Para `dpo.test` y `admin.test` calcula el código TOTP (HMAC-SHA256, 6 dígitos, 30 s) con el secreto de `deploy/dev/keycloak/realm-argos.json`.

| Token | Usuario | Rol | Segundo factor |
|---|---|---|---|
| `token_manager` | manager.test | campaign_manager | no |
| `token_dpo` | dpo.test | dpo_reviewer | sí |
| `token_admin` | admin.test | platform_admin | sí |
| `token_auditor` | auditor.test | read_only_auditor | no |

## Aviso

Solo desarrollo: usuarios, contraseña y secretos TOTP son los del realm de desarrollo, que ya están en este repositorio. No usar contra un appliance de cliente. La exportación no debe llevar tokens: antes de volver a commitear el archivo, vacía las variables `token_*`.
