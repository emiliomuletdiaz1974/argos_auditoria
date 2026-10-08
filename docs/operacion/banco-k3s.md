# Prueba del banco k3s (K-99)

**Fecha:** 2026-10-07 · **Versión desplegada:** `banco-v0.18.2` · **Confidencialidad:** `internal`

El banco es una VM de Google Cloud (`e2-highmem-8`, sin GPU) con k3s, Flux y **solo datos sintéticos** (nota de desviación [ARG-002-003](../desviaciones/ARG-002-003.md) §7). Este informe recoge qué probamos sobre él, con qué y qué encontramos. No es el piloto: el piloto espera a que el organismo apruebe dónde van sus datos.

## 1. Cómo lo probamos

- **Red (F1-11b):** desde dentro de cuatro pods (`api`, `verifier`, `challenge-worker` y la siembra clínica), conexiones a cada servicio de `argos-core` y `bench-sources`, por puerto. Por SSH, solo lectura.
- **Campaña y accesos:** la colección `tools/postman/ARGOS-API-v1.postman_collection.json` con el entorno `ARGOS-banco.postman_environment.json`, lanzada por una persona desde su equipo contra `https://api.34-134-21-66.sslip.io` (por túnel SSH mientras la empresa no abra los puertos 80/443). Las cuentas son las del realm del banco (`accounts.sh`), con contraseña y TOTP de quien las usa. Nosotros no usamos las cuentas: seguimos las peticiones en el log de la API y comprobamos el resultado en la base de datos.
- La batería automática de `tests/security/test_access_battery.py` **no** se ejecutó contra el banco. Está atada al entorno de desarrollo (contraseñas fijas, secretos TOTP del realm de desarrollo y lectura directa de la base), y para el banco la sustituye la carpeta 12 de la colección.

## 2. Resultados

| Comprobación | Resultado |
|---|---|
| Red denegada por defecto (F1-11b) | 37 de 37 conexiones como deben: lo permitido llega y lo demás se corta |
| Carpeta 10 · operación y registro de seguridad (administrador con TOTP) | 4/4 en 200 |
| Carpeta 03 · campaña completa (gestor crea y lanza, DPO con TOTP aprueba) | 3 campañas selladas seguidas (`01a1192d…`, `01a11935…`, `01a1194d…`) |
| Una campaña sellada | 53 veredictos (31 no conformes, 19 conformes, 3 no concluyentes), raíz de Merkle de 53 hojas, 53 artefactos en el almacén WORM, expediente JSON y PDF, credencial emitida |
| Carpeta 04 · hallazgos | 31 hallazgos abiertos (19 altos, 12 medios); transiciones y petición de verificación correctas; la aceptación de riesgo desde `pending_verification` se rechaza (409) |
| Verificación de una subsanación | la petición crea la reejecución (`01a1192f…`), que espera al DPO en la compuerta de inicio como cualquier campaña; aprobada, corre solo la unidad no conforme, se sella con 1 veredicto `non_compliant` y el hallazgo pasa de `pending_verification` a `reopened` (en las fuentes sintéticas no se corrigió nada) |
| Carpeta 05 · evidencia | 7/7 en 200: cadena, artefactos, artefacto con prueba de inclusión, asiento del diario citado, expediente JSON y PDF, paquete del comprobador |
| Carpeta 06 · credenciales | vista previa 200, emisión 201, lectura 200, revocación 200 |
| Carpeta 12 · lo que debe fallar | sin token 401, token falso 401, rol sin permiso 403, aprobar sin ser DPO 403, cierre manual de un hallazgo 409, webhook a un destino no permitido 422, cursor inválido 400, ruta inexistente 404, refresco sin cookie 401 |
| Registro de seguridad tras la carpeta 12 | `auth.token_missing` 2, `auth.token_rejected` 2, `authz.denied` 4 (rechazados) y `authz.admin_action` 3 (permitidos y anotados) |
| El front desde `http://localhost:5173` | sesión, sistemas, inventario (grafo, cobertura y nodos), campañas y hallazgos en 200, con CORS |

## 3. Qué encontramos y corregimos

| Commit | Hallazgo |
|---|---|
| `c1bc486` | La página de cuenta de Keycloak respondía 401: las cuentas no llevaban `default-roles-argos` y el token no traía la audiencia `account`. |
| `f624c20` | **Ninguna campaña llegaba a prepararse.** El motor compara las políticas que ejecuta OPA con el paquete de contenido firmado y deja fuera solo el montaje `auth` (SEC-011). En la imagen de OPA del banco, la regla de acceso de OPA estaba en `/authz`, contaba como una política sin firmar, y `prepare_campaign` fallaba con «OPA is not running the signed bundle». Pasa a `/auth`, como en desarrollo, con un test sobre la imagen y el Deployment. El control funcionó como debe: una política fuera del paquete firmado paró la campaña y dejó `content.policies_mismatch` en el registro de seguridad. |
| `7c5d05b` | La colección no podía probar el asiento del diario citado: la lista de veredictos no trae su número, y solo 22 de 53 veredictos citan uno, porque las sondas internas no consultan ninguna fuente. Ahora la toma del primer artefacto que lo cita. |
| `ccf65be`, `46c57df` | Las peticiones «Token ·» de la colección solo servían en desarrollo: leían el secreto TOTP en bruto y la contraseña común. Ahora prueban antes la clave Base32 y la contraseña de cada rol del entorno del banco, como ya hacía el script general de la colección. |

Antes de K-99, en la misma etapa: el arranque idempotente frente a Vault, la reutilización de las imágenes de infraestructura por huella, la estrategia `Recreate` en los suscriptores duraderos de NATS y la publicación del contenido firmado en el arranque (bitácora del 2026-10-06).

## 4. Lo que la colección enseña y no es un fallo

- El plan previo responde 409 cuando el Runner lo pide justo después de lanzar: la campaña aún no está preparada.
- Las peticiones de la carpeta 05 aceptan 200 o 404: un «PASS» con 404 significa que no había campaña o veredicto en las variables, no que la evidencia funcione.
- Al reimportar la colección, Postman borra sus variables (`campaign_id`, `verdict_id`, `finding_id`, `journal_seq`).
- La verificación de una subsanación no corre sola: espera la aprobación del DPO, como cualquier campaña (SEC-010). Si nadie aprueba, la campaña se queda en `pinned` y el hallazgo en `pending_verification`.

## 5. Lo que queda fuera o pendiente

- Sin GPU: el asistente y la clasificación asistida responden 503 (F06-05).
- Vault y OPA hablan HTTP dentro del clúster, y por eso el banco corre en `staging` y no en `production`.
- La entrada pública espera a que la empresa abra los puertos 80/443. Hasta entonces, túnel SSH.
- El sujeto sintético (carpeta 07) y el asistente (carpeta 08) no se recorrieron en esta prueba.
