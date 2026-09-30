# Colección de Postman de la API v1

`ARGOS-API-v1.postman_collection.json` recorre las 54 operaciones del contrato `services/api/openapi.json` en 68 peticiones organizadas en 14 carpetas. Sirve para probar a mano la API en el **entorno de desarrollo** (`make dev`).

## Uso

1. Levanta el entorno: `make dev`. Si faltan las fuentes simuladas: `uv run --env-file .env.example python tools/register_dev_sources.py`.
2. Importa el archivo en la aplicación de escritorio de Postman. El navegador no deja cambiar la cabecera `Host` que necesitan los tokens.
3. Pon los dos secretos TOTP en la pestaña **Variables** de la colección, en la columna **Current value** (valor actual, local), y deja vacía **Initial value**:
   - `totp_secret_dpo`: el `secretData` del usuario `dpo.test` en `deploy/dev/keycloak/realm-argos.json`;
   - `totp_secret_admin`: el de `admin.test`.

   El valor actual se queda en tu Postman: ni se exporta ni se versiona. Si falta, la petición se para con un error que dice cuál falta. Al volver a importar la colección hay que ponerlos otra vez.
4. Ejecuta **00 · Preparación y tokens → Salud de la API** y después las carpetas en orden.

## Autenticación

Cada petición declara su rol (`{{token_manager}}`, `{{token_dpo}}`, `{{token_admin}}` o `{{token_auditor}}`) y el script de la colección pide el token a Keycloak con el cliente `argos-tests`, con `Host: keycloak:8080` para que el emisor coincida con `ARGOS_OIDC_ISSUER`. Para `dpo.test` y `admin.test` calcula el código TOTP (HMAC-SHA256, 6 dígitos, 30 s) con los secretos que pusiste como valor actual (paso 3).

| Token | Usuario | Rol | Segundo factor |
|---|---|---|---|
| `token_manager` | manager.test | campaign_manager | no |
| `token_dpo` | dpo.test | dpo_reviewer | sí |
| `token_admin` | admin.test | platform_admin | sí |
| `token_auditor` | auditor.test | read_only_auditor | no |

## Aviso

Solo desarrollo: usuarios y contraseña son los del realm de desarrollo. No usar contra un appliance de cliente. Los secretos TOTP solo están en `realm-argos.json`, y `tests/integration/test_keycloak_mfa.py` falla si aparecen en otro archivo del repositorio. La exportación no debe llevar tokens ni secretos: antes de volver a commitear el archivo, deja vacías las variables `token_*` y `totp_secret_*`.
