# Manual de usuario · ARGOS con Postman y Keycloak

Versión 1.0 · 9 de octubre de 2026 · Solo para entornos con datos sintéticos (banco k3s y desarrollo)

**Para quién:** quien vaya a usar ARGOS en el banco de pruebas sin que nadie le guíe, quien pruebe la API a mano o quien integre el front. No hace falta conocer el código ni Kubernetes; basta con saber qué es una petición HTTP.

**Datos:** todo lo que hay en el banco es sintético. Se puede crear, aprobar y romper sin miedo, salvo lo marcado como **irreversible**.

---

## 1. Qué es ARGOS y qué vas a usar

ARGOS audita sistemas que tratan datos personales. Descubre qué datos hay (**inventario**), lanza una **campaña** de comprobaciones de solo lectura contra la normativa (RGPD, EHDS, AI Act), saca **veredictos** y **hallazgos**, y lo sella todo en un **expediente** firmado del que se puede emitir una **credencial verificable**.

En el banco no hay pantallas propias de ARGOS: el front lo construye otro equipo. Se usa con estas piezas:

| Pieza | Para qué sirve |
|---|---|
| **Keycloak** | El servidor de identidad. Guarda las cuentas, comprueba la contraseña y el segundo factor, y emite los tokens que acepta la API. Ahí eliges tu contraseña y configuras el segundo factor. |
| **API de ARGOS** | La API única (`/api/v1`). Solo responde a peticiones con un token válido de Keycloak. |
| **Postman (escritorio)** | El cliente con el que haces las peticiones. La colección ya trae todas las peticiones, en orden, y pide los tokens a Keycloak por ti. |
| **Autenticador TOTP** | La aplicación del móvil que genera el código de 6 dígitos del segundo factor (solo DPO y administrador). |

Los archivos de Postman están en el repositorio, en `argos/tools/postman/` (o te los pasamos):

- `ARGOS-API-v1.postman_collection.json`: la colección, con 68 peticiones en 14 carpetas que cubren las 54 operaciones del contrato.
- `ARGOS-banco.postman_environment.json`: el entorno del banco, con las direcciones y los huecos para contraseñas y claves.

## 2. Requisitos previos

1. **Postman de escritorio.** La versión web no sirve: el navegador no deja cambiar la cabecera `Host`, y la colección la necesita para pedir los tokens.
2. **Un autenticador compatible con HMAC-SHA256**, si vas a usar una cuenta de DPO o de administrador: **FreeOTP, Aegis o 2FAS**. Google Authenticator y Microsoft Authenticator calculan con SHA-1 y sus códigos **no valen**, aunque parezcan correctos.
3. **Tus cuentas del banco** y sus contraseñas temporales. Te las da quien administra el banco. Cada contraseña temporal sirve **una sola vez**.
4. **Conexión a internet.** El banco se publica por HTTPS con certificados de Let's Encrypt: no hace falta VPN, túnel ni tocar la configuración del equipo.

### 2.1 Comprobar que llegas

Abre en el navegador `https://api.34-134-21-66.sslip.io/health`. Debe mostrar un JSON con el estado de la API, sin ningún aviso de certificado. Si no carga, o el navegador avisa de que el certificado no es de confianza, avisa a quien administra el banco antes de seguir.

### 2.2 Direcciones del banco

| Qué | Dirección |
|---|---|
| API | `https://api.34-134-21-66.sslip.io/api/v1` |
| Keycloak · realm `argos` | `https://id.34-134-21-66.sslip.io/realms/argos` |
| Keycloak · tu cuenta (contraseña y TOTP) | `https://id.34-134-21-66.sslip.io/realms/argos/account` |
| Catálogo normativo (sin cuenta) | `https://ns.34-134-21-66.sslip.io/norms/` |

---

## 3. Keycloak en cinco minutos

### 3.1 Conceptos

- **Realm `argos`**: el espacio de Keycloak donde viven las cuentas, los roles y los clientes de ARGOS. Todo lo de este manual ocurre en ese realm.
- **Cliente**: la aplicación que pide los tokens. Te interesan dos:
  - `argos-tests`: el de Postman y los tests. Admite el flujo *password*: usuario, contraseña y código TOTP, directamente.
  - `argos-console`: el del front web. Usa el flujo del navegador con PKCE; desde Postman solo sirve de referencia (carpeta 13).
- **Token de acceso**: un JWT firmado por Keycloak que lleva tus roles. Dura **5 minutos**, y la colección lo renueva sola.
- **Segundo factor (TOTP)**: un código de 6 dígitos que cambia cada 30 s. Las acciones que **deciden** exigen un token emitido con TOTP: aprobar, emitir, revocar, mover hallazgos, registrar sistemas… Si el token no lo lleva, la API responde `401` con `insufficient_user_authentication` en la cabecera `WWW-Authenticate`.
- Keycloak del banco está **en inglés**: los nombres de botones de este manual son los que verás.

### 3.2 Cuentas y roles del banco

ARGOS separa los deberes: **quien pide una cosa no puede aprobarla**, y nadie aprueba dos veces la misma compuerta. Por eso, para recorrer el flujo completo hacen falta al menos dos cuentas, la del gestor y la del DPO. Una misma cuenta no puede tener a la vez el rol de gestor y el de DPO: la API la rechaza.

Cada grupo tiene sus propias cuentas, una por rol. Usa **solo las de tu grupo**: el registro de seguridad apunta quién hizo cada cosa.

| Rol | Qué puede hacer | TOTP | Equipo de ARGOS | Equipo del front | Probador externo |
|---|---|---|---|---|---|
| `campaign_manager` (gestor) | Planificar y lanzar campañas, pedir la verificación de una subsanación, confirmar los pasos del sujeto sintético | no | `manager.test` | `front.manager` | `guest.manager` |
| `dpo_reviewer` (delegado de protección de datos) | Aprobar compuertas, decidir columnas del inventario, mover hallazgos, emitir credenciales | **sí** | `dpo.test` y `dpo2.test` | `front.dpo` | `guest.dpo` |
| `platform_admin` (administrador) | Registrar sistemas y webhooks, revocar credenciales, soporte, actualizaciones y esclusa | **sí** | `admin.test` | `front.admin` | `guest.admin` |
| `read_only_auditor` (auditor) | Solo lectura | no | `auditor.test` | `front.auditor` | `guest.auditor` |

La compuerta `sampling` pide **dos DPO distintos**. Cada grupo tiene uno, así que si aparece, la segunda aprobación la da el equipo de ARGOS (§6).

En el resto del manual, «`manager.test`», «`dpo.test`»… quiere decir **la cuenta de ese rol de tu grupo**.

---

## 4. Primer acceso a Keycloak (una vez por cuenta)

Hazlo en el navegador **antes** de usar Postman. Si no, la colección no podrá pedir tokens: Keycloak no emite tokens a una cuenta con acciones pendientes (cambiar la contraseña, configurar el TOTP).

### 4.1 Cambiar la contraseña temporal

1. Abre `https://id.34-134-21-66.sslip.io/realms/argos/account`.
2. Entra con tu cuenta (por ejemplo `guest.dpo`) y la contraseña temporal.
3. Keycloak te pide una contraseña nueva (**«Update password»**). Escríbela dos veces y guárdala en tu gestor de contraseñas: es la que irá en Postman.

### 4.2 Configurar el segundo factor (solo las cuentas de DPO y de administrador)

1. Justo después del cambio de contraseña, Keycloak muestra la pantalla **«Mobile Authenticator Setup»** con un código QR.
2. Abre FreeOTP, Aegis o 2FAS y escanea el QR.
3. **Muy importante para Postman:** pulsa **«Unable to scan?»**. Keycloak muestra la **clave en Base32**: letras de la A a la Z y dígitos del 2 al 7, en grupos. **Cópiala**: es lo que Postman necesita para calcular los códigos (`totp_key_dpo` o `totp_key_admin`). Comprueba en esa misma pantalla que el algoritmo es **SHA256**, con 6 dígitos y 30 s.
4. Escribe el código de 6 dígitos que muestra el autenticador y un nombre para el dispositivo (por ejemplo «Postman + móvil»). Pulsa **Submit**.

> La clave Base32 es un secreto equivalente a tu móvil: con ella cualquiera genera tus códigos. Guárdala solo en el gestor de contraseñas y en el **valor actual** de Postman (§5.2). Nunca en un archivo del repositorio ni en una captura.

### 4.3 Comprobar que funciona

Cierra sesión en la página de cuenta y vuelve a entrar: debe pedirte la contraseña y luego el código. Si entras, la cuenta está lista.

### 4.4 Qué más puedes hacer en la página de cuenta

- **Personal info:** nombre y apellidos. Son los que aparecen como aprobador en el expediente PDF.
- **Account security → Signing in:** cambiar la contraseña y ver o quitar el autenticador.
- **Account security → Device activity:** ver las sesiones abiertas y cerrarlas.

La consola de administración de Keycloak no está publicada en el banco.

### 4.5 Bloqueos: «temporarily disabled» frente a «disabled»

| Mensaje de Keycloak | Qué pasa | Qué hacer |
|---|---|---|
| «Account is temporarily disabled…» | Cinco intentos fallidos seguidos. El bloqueo empieza en 60 s y crece hasta 15 min. | Esperar. No pidas un reinicio mientras sigues probando contraseñas. |
| «Account is disabled, contact your administrator» | La cuenta está deshabilitada y no se recupera sola. | Pide al administrador que la reinicie (§4.6). |
| «Invalid username or password» con la contraseña buena | Casi siempre es el código TOTP: ya se usó en esta ventana de 30 s, o el autenticador es SHA-1. | Espera al siguiente código; revisa el autenticador (§2). |

### 4.6 Reiniciar una cuenta (lo hace el administrador del banco)

Si pierdes la contraseña, el móvil o la clave TOTP, o la cuenta queda deshabilitada, el administrador ejecuta en la VM:

```bash
bash platform/k8s/bench/accounts.sh reset dpo.test
```

Eso da una contraseña temporal nueva, desbloquea y habilita la cuenta, y obliga a configurar el TOTP otra vez. Después repites §4.1 a §4.3 y **actualizas en Postman** la contraseña y la clave Base32, porque la vieja deja de valer.

---

## 5. Preparar Postman (una vez)

### 5.1 Importar

1. **Import → File** y elige `ARGOS-API-v1.postman_collection.json`.
2. Otra vez **Import → File** con `ARGOS-banco.postman_environment.json`.
3. Arriba a la derecha, en el selector de entornos, elige **«ARGOS · banco (k3s, datos sintéticos)»**.

Deja activada la verificación de certificados de Postman (**Settings → General → SSL certificate verification**): el banco tiene certificados públicos.

### 5.2 Rellenar contraseñas y claves

En el entorno del banco (icono del ojo → **Edit**), rellena **solo la columna «Current value»** y deja vacía «Initial value»:

| Variable | Qué poner | Ejemplo para el probador externo |
|---|---|---|
| `user_manager` | Tu cuenta de gestor | `guest.manager` |
| `user_dpo` | Tu cuenta de DPO | `guest.dpo` |
| `user_admin` | Tu cuenta de administrador (si la usas) | `guest.admin` |
| `user_auditor` | Tu cuenta de auditor | `guest.auditor` |
| `password_manager` | Contraseña definitiva de tu gestor | — |
| `password_dpo` | Contraseña definitiva de tu DPO | — |
| `password_admin` | Contraseña definitiva de tu administrador (si la usas) | — |
| `password_auditor` | Contraseña definitiva de tu auditor | — |
| `totp_key_dpo` | Clave Base32 de tu DPO (§4.2, paso 3) | — |
| `totp_key_admin` | Clave Base32 de tu administrador (si la usas) | — |

Si dejas vacío un `user_<rol>`, la colección usa la cuenta del equipo de ARGOS (`manager.test`, `dpo.test`…). Las peticiones de la carpeta 00 se siguen llamando **Token · manager.test**, **Token · dpo.test**…, pero entran con la cuenta que pongas aquí.

El **valor actual** se queda en tu Postman: no se sincroniza, no se exporta y no se versiona. El **valor inicial** sí viajaría al exportar o compartir el entorno; por eso va vacío. Las variables ya están marcadas como `secret`, así que Postman las oculta en pantalla. Las cuentas que no vayas a usar se dejan vacías.

Las variables que ya trae el entorno no se tocan: `baseUrl`, `keycloakUrl`, `keycloakHost` y `keycloakClient` (`argos-tests`). Guarda el entorno con Ctrl+S.

### 5.3 Primera prueba

1. Ejecuta **00 · Preparación y tokens → Salud de la API**. Debe responder `200`. Si no, vuelve a §2.1.
2. Ejecuta **Token · manager.test**. Debe responder `200` con un `access_token`.
3. Ejecuta **Token · dpo.test** y, si lo usas, **Token · admin.test**. También `200`.
4. Abre la consola de Postman (**View → Show Postman Console**, o `Ctrl+Alt+C`). Cada petición de token escribe ahí los roles y el `amr` del token. Para el DPO y el administrador, `amr` debe contener `otp`.

---

## 6. Cómo funciona la autenticación automática

No hace falta copiar tokens. Cada petición lleva una cabecera como esta:

```
Authorization: Bearer {{token_dpo}}
```

Antes de enviarla, el script de la colección hace esto:

1. Mira qué rol pide la cabecera (`manager`, `dpo`, `admin` o `auditor`).
2. Si ese token no existe, caduca en menos de 20 s o es de otra cuenta que la de `user_<rol>`, lo pide a Keycloak: `POST {{keycloakUrl}}/realms/argos/protocol/openid-connect/token` con el cliente `argos-tests`, el usuario y la contraseña del entorno. Para el DPO y el administrador añade el **código TOTP**, que calcula a partir de la clave Base32 (HMAC-SHA256, 6 dígitos, 30 s).
3. Guarda el token y su caducidad en las variables de la colección (`token_<rol>` y `token_<rol>_exp`).

Keycloak **no acepta dos veces el mismo código TOTP** dentro de la misma ventana de 30 s. Si el script ya usó el código de la ventana actual, espera a la siguiente antes de pedir el token, así que alguna petición puede tardar hasta 30 s. Es normal.

**Forzar un token nuevo:** ejecuta a mano la petición **Token · <cuenta>** de la carpeta 00, o borra el valor de `token_<rol>` en la pestaña **Variables** de la colección.

**Segunda aprobación de la compuerta `sampling`:** la da otra persona con rol DPO, normalmente el equipo de ARGOS con `dpo2.test`. Desde su propio Postman, o desde el tuyo cambiando de cuenta:

1. En el entorno, pon en `user_dpo`, `password_dpo` y `totp_key_dpo` los de la segunda cuenta de DPO.
2. Duplica **Aprobar compuerta start**, cambia `start` por `sampling` en la URL y envíala. La colección ve que el usuario ha cambiado y pide un token nuevo.
3. Vuelve a poner tu cuenta en esas tres variables.

La misma cuenta no puede aprobar dos veces: la API lo rechaza con `409`.

**Dónde mirar si algo falla:** en la consola de Postman (`Ctrl+Alt+C`) sale el error completo de la API o el de Keycloak.

---

## 7. Qué hay en cada carpeta

La colección está numerada en el orden en que se usa. Junto a cada petición pone qué cuenta la hace; las que llevan «2FA» usan el segundo factor.

| Carpeta | Para qué sirve | Quién |
|---|---|---|
| **00 · Preparación y tokens** | Comprueba que la API responde y pide los tokens de cada cuenta. Úsala para saber si tus contraseñas y claves están bien. | todos |
| **01 · Sistemas** | Los sistemas que ARGOS audita (bases de datos, ficheros, directorio y fuentes clínicas, todo simulado): listarlos y registrar nuevos. | auditor lee; admin (2FA) registra |
| **02 · Inventario** | Qué datos personales se han descubierto: cobertura por sistema, cola de columnas que el clasificador no supo decidir con su revisión por el DPO, y el detalle de cada elemento. | auditor, DPO (2FA) |
| **03 · Campañas (flujo completo)** | El núcleo de ARGOS: planificar, lanzar, ver el plan previo, aprobar la compuerta, seguir el progreso, leer los veredictos y reejecutar. | gestor, DPO (2FA), auditor |
| **04 · Hallazgos** | Los incumplimientos encontrados, del peor al menos grave, con su porqué: moverlos de estado, aceptar el riesgo y verificar la subsanación. | auditor, DPO (2FA), gestor |
| **05 · Evidencia** | La cadena de prueba de una campaña sellada: artefactos, árbol de Merkle, prueba de inclusión, diario, el **expediente** en JSON y en PDF, y el paquete para el comprobador público. | auditor |
| **06 · Credenciales verificables** | Ver qué afirmaría la credencial, emitirla, consultar su estado y revocarla. La revocación es **irreversible**. | DPO (2FA) emite; admin (2FA) revoca |
| **07 · Sujeto sintético** | Medir un derecho (por ejemplo, la supresión) con un sujeto inventado: autorizar la inyección y confirmar cada paso. Necesita un sujeto ya generado y no forma parte del recorrido básico. | DPO (2FA), gestor |
| **08 · Asistente** | Preguntar al asistente. **En el banco responde 503** porque no hay modelo de IA; es lo esperado. | gestor |
| **09 · Webhooks e ITSM** | Avisos a sistemas externos (Jira, ServiceNow): suscribir, listar y ver entregas. Opcional. | admin (2FA) |
| **10 · Operación y registro de seguridad** | Semáforos del sistema, capacidad, runbooks y registro de seguridad (quién entró y qué se denegó). | auditor, admin |
| **11 · Soporte, actualizaciones y esclusa** | Operaciones de plataforma: diagnóstico, actualizaciones y soportes. Mejor no tocarla en una primera visita. | admin (2FA) |
| **12 · Pruebas de seguridad (deben fallar)** | Intentos indebidos: sin token, token falso, el auditor creando, el gestor aprobando lo suyo, cerrar un hallazgo a mano… **Todos deben dar error.** | varios |
| **13 · Sesión de la consola (referencia)** | Rutas OIDC con PKCE que usa el front; desde Postman solo sirven de referencia. | — |

En el banco, lo prioritario es **03 → 06** y **12**.

**Variables encadenadas:** las peticiones se pasan los identificadores mediante variables de la colección (`system_id`, `campaign_id`, `finding_id`, `verdict_id`, `journal_seq`, `node_key`, `credential_id`, `webhook_id`…). Por eso conviene ejecutar cada carpeta **en orden**. Puedes fijar cualquiera a mano en la pestaña **Variables** de la colección, por ejemplo para trabajar sobre una campaña ya sellada.

---

## 8. Recorrido de una campaña de principio a fin

Ejecuta las peticiones **en este orden** con **Send**. Los identificadores se guardan solos de una petición a la siguiente.

> Varias peticiones **modifican datos**: crean campañas, sistemas y webhooks, deciden columnas, mueven hallazgos o revocan credenciales. Su descripción en Postman lo indica.

### Paso 1 · Comprobar que todo está listo (carpeta 00)
1. **Salud de la API** → `200`.
2. **Token · manager.test** y **Token · dpo.test** → `200` las dos. Si alguna falla, revisa §5 antes de seguir.

### Paso 2 · Elegir el sistema (carpeta 01)
3. **Listar sistemas** (auditor) → `200`. Guarda el primero en `system_id`. Son las fuentes sintéticas del banco.

### Paso 3 · Ver qué datos hay (carpeta 02, opcional pero recomendable)
4. **Cobertura y frescura** → qué se ha explorado y cuándo.
5. **Cola de revisión del DPO** (DPO) → las columnas dudosas.
6. **Detalle de un nodo** → de dónde sale cada dato y su historia.
7. **Decidir una columna** (DPO, 2FA) → el DPO confirma o corrige la categoría, y queda registrado.

### Paso 4 · Planificar y lanzar (carpeta 03)
8. **Planificar campaña** (gestor) → `201`. La campaña cubre el sistema del paso 2. Lleva `Idempotency-Key`: si la repites con la misma clave, no se crea otra.
9. **Lanzar campaña** (gestor) → `200`. ARGOS arranca el workflow, prepara qué va a preguntar y se detiene en la compuerta `start`.
10. **Plan previo** (auditor) → `200` con **la lista literal de consultas** que se harán a cada sistema, antes de hacer ninguna. Si responde `409`, aún se está preparando: espera 10 s y repite.
11. **Compuertas** (auditor) → la compuerta `start` aparece pendiente, con quién ha aprobado y cuántas aprobaciones faltan.

### Paso 5 · Aprobar (carpeta 03, como DPO)
12. **Aprobar compuerta start** (DPO, 2FA) → `200`. Desde aquí la campaña ejecuta sus sondas.
    - Prueba antes, en la carpeta 12, **«Manager intenta aprobar su compuerta»**: da `403`. Quien lanza no aprueba.
    - Si en **Compuertas** aparece además la compuerta `sampling`, esa exige **dos DPO distintos**: duplica **Aprobar compuerta start** y cambia `start` por `sampling` en la URL, apruébala con tu DPO y pide la segunda aprobación al equipo de ARGOS (§6).

### Paso 6 · Seguir la ejecución
13. **Progreso** → unidades hechas frente a totales. Repítelo cada pocos segundos.
14. **Estado de la campaña** → pasa por `running` y termina en **`sealed`** (sellada) en unos minutos. Con `sealed`, `seal_verified: true` indica que la API ha vuelto a comprobar el sello.
15. **Veredictos** → uno por comprobación: conforme, no conforme, no demostrado o no concluyente. Los produce un evaluador determinista; la IA no interviene en ningún veredicto.

### Paso 7 · Hallazgos (carpeta 04)
16. **Listar hallazgos (peor primero)** → los no conformes convertidos en tareas. Guarda el primero.
17. **Detalle de un hallazgo** → el porqué completo: criterio, valor observado, muestra, obligación con su artículo e historia de estados.
18. **Pasar a remediación** (DPO, 2FA) → `in_remediation`.
19. **Marcar como subsanado** (DPO, 2FA) → `pending_verification`.
20. **Verificar la subsanación** (gestor) → crea una reejecución solo de esa comprobación.
    - Es otra campaña pequeña que **también espera al DPO en su compuerta `start`**: apruébala como en el paso 12.
    - Cuando se selle, el hallazgo pasa a `closed_compliant` si ya cumple, o a `reopened` si no. En el banco nadie corrige las fuentes, así que lo normal es `reopened`.
    - Nadie puede cerrar un hallazgo a mano: en la carpeta 12, **«Cierre manual de un hallazgo»** da `409` o `422`.
    - Alternativa: **Aceptar el riesgo** (DPO, 2FA), con nota y fecha de caducidad. Al caducar, el hallazgo se reabre solo.

### Paso 8 · Evidencia y expediente (carpeta 05)
21. **Cadena de evidencia** → cada eslabón con su estado real. En el banco la firma es de una clave de pruebas, y la API lo dice así.
22. **Expediente (PDF)** → en Postman, **Save response → Save to a file**, y ábrelo. Es el documento para personas: resumen, problemas agrupados, aprobaciones y un QR al comprobador público.
23. **Expediente (JSON canónico)** y **Paquete para el comprobador público** → lo que un tercero verifica sin acceso a ARGOS.

### Paso 9 · Credencial (carpeta 06)
24. **Vista previa de la credencial** (DPO, 2FA) → exactamente lo que se va a afirmar.
25. **Emitir la credencial** (DPO, 2FA) → `201`. Si responde `409`, el expediente ha cambiado desde la vista previa: vuelve a leerla.
26. **Estado de la credencial** → vigente.
27. **Revocar la credencial** (admin, 2FA): **irreversible**. No hace falta para el recorrido.

### Paso 10 · Lo que debe fallar (carpeta 12)
28. Ejecuta la carpeta entera (§8.1). Todas las peticiones deben salir rechazadas (`401`, `403`, `400`, `404`, `409` o `422`). En la pestaña **Test Results** de cada una pone qué código se esperaba. **Si alguna pasa, es un fallo de seguridad** y hay que avisar.

### 8.1 Ejecutar una carpeta entera

Botón derecho sobre la carpeta → **Run folder**. El Collection Runner ejecuta las peticiones en orden y muestra los tests de cada una. En la carpeta 03, añade un retardo (**Delay**) de 2 a 3 s entre peticiones para dar tiempo a que la campaña se prepare.

---

## 9. Leer las respuestas y los errores

- **Errores:** todos llegan en `application/problem+json` (RFC 9457), con `type`, `title`, `status` y `detail`. Estamos añadiendo un campo `code` estable en inglés y los textos en castellano. La colección escribe cada error en la consola de Postman con el nombre de la petición.
- **Tests:** cada petición comprueba el código de respuesta esperado; lo verás en la pestaña **Test Results**.
- **Paginación:** los listados usan un cursor opaco. Si la respuesta trae `next`, pásalo como parámetro `cursor` en la petición siguiente. `limit` admite de 1 a 100.

### 9.1 Códigos más frecuentes

| Código | Significado habitual |
|---|---|
| `401` sin más | Token ausente, caducado o no firmado por Keycloak |
| `401` con `insufficient_user_authentication` | La acción exige segundo factor y el token no lo lleva (falta la clave TOTP o es incorrecta) |
| `403` | Tu rol no tiene ese permiso, o la separación de deberes lo impide |
| `404` | No existe, o aún no hay campaña sellada (evidencia y credenciales) |
| `409` | Estado incompatible: campaña aún preparándose, ya lanzada, expediente cambiado… |
| `422` | Cuerpo inválido (por ejemplo, un webhook a una dirección interna) |
| `429` | Cupo o límite de la talla agotado |
| `503` | Servicio no disponible (en el banco, el asistente) |

### 9.2 Respuestas que parecen errores y no lo son

| Respuesta | Dónde | Significado |
|---|---|---|
| `409` | Plan previo | La campaña aún se está preparando. Repite en unos segundos. |
| `409` | Progreso | La campaña no está en marcha: aún no se ha aprobado, o ya está sellada. |
| `404` / `409` | Evidencia y credencial | La campaña aún no está sellada. |
| `501` | Aprobaciones pendientes del DPO | La ruta está declarada y sin implementar a propósito. Las compuertas se ven en **Compuertas** de cada campaña. |
| `503` | Asistente | No hay modelo de IA en el banco. |
| `429` / `409` | Lanzar campaña | Ya hay demasiadas campañas en paralelo para la talla del banco. Espera a que termine alguna. |
| Test rojo «El emisor es el que valida la API» | Peticiones de token, en el banco | Ese test compara con `http://` y el banco emite con `https://`. No afecta: el token se guarda igual y la API lo acepta. |

---

## 10. Resolución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| Todas las peticiones fallan con un error SSL, o `ECONNREFUSED`, o tiempo agotado | El banco no responde desde tu red, o un proxy o antivirus intercepta HTTPS | Comprueba §2.1 en el navegador; si allí tampoco, avisa a quien administra el banco |
| «ARGOS · falta totp_secret_dpo … o totp_key_dpo» | No pusiste la clave Base32 como valor actual | §5.2 |
| «ARGOS · la clave TOTP no es Base32» | Copiaste algo que no es la clave: espacios raros, el QR o un código de 6 dígitos | Vuelve a copiarla desde «Unable to scan?». Si no la tienes, pide un reinicio (§4.6). |
| La petición de token responde `401` `invalid_grant` | Contraseña equivocada, cuenta con acciones pendientes o código TOTP rechazado | Entra en el navegador (§4); espera 30 s y repite |
| La petición de token responde `400` «Account is not fully set up» | Falta cambiar la contraseña o configurar el TOTP | §4.1 y §4.2 en el navegador |
| Los códigos TOTP nunca valen | Autenticador SHA-1 (Google o Microsoft Authenticator) o reloj del equipo desajustado | Usa FreeOTP, Aegis o 2FAS; sincroniza la hora de Windows y del móvil |
| La API responde `401` con un token recién pedido | El reloj del equipo va desfasado | Pon la hora automática |
| Una acción responde `401` con `insufficient_user_authentication` | El token del rol se pidió sin TOTP | Borra `token_<rol>` en Variables y repite |
| «Account is temporarily disabled» | Cinco intentos fallidos | Espera hasta 15 min (§4.5) |

---

## 11. Buenas prácticas de seguridad

- Rellena contraseñas y claves **solo en «Current value»**, nunca en «Initial value».
- **No exportes** la colección ni el entorno con valores puestos. Si hay que volver a versionar un archivo de Postman, deja vacías antes las variables `token_*`, `totp_secret_*`, `totp_key_*` y `password_*`.
- No pegues tokens ni claves en chats, tickets ni capturas. Un token de acceso vale 5 minutos, pero una clave TOTP vale hasta que se reinicie la cuenta.
- Al terminar, cierra sesión en Keycloak desde la página de cuenta (**Account security → Device activity → Sign out all devices**). Si el equipo no es tuyo, borra también los «Current value» del entorno.
- Estas cuentas y esta colección son **solo para entornos con datos sintéticos**. No se usan contra el appliance de un cliente.
- El catálogo normativo es público y no necesita cuenta: `https://ns.34-134-21-66.sslip.io/norms/`. Ahí se abren las obligaciones que citan los hallazgos.

---

## Anexo A · Entorno de desarrollo local (`make dev`)

Para quien trabaja con el repositorio en su equipo:

1. En `argos/`: `make dev`. Si faltan las fuentes simuladas: `uv run --env-file .env.example python tools/register_dev_sources.py`.
2. Importa solo la colección y **no** selecciones el entorno del banco: las variables de la colección ya apuntan a `http://127.0.0.1:8000` y `http://127.0.0.1:8180`.
3. La contraseña de las cuentas de desarrollo está en la variable `password` de la colección.
4. En **Variables** de la colección, como **Current value**, pon `totp_secret_dpo` y `totp_secret_admin`: el `secretData` de `dpo.test` y de `admin.test` en `deploy/dev/keycloak/realm-argos.json`. Aquí va el secreto **tal cual**, no en Base32.
5. La petición de token lleva `Host: keycloak:8080` para que el emisor del token coincida con el que valida la API dentro de Docker. Por eso hace falta Postman de escritorio.
6. Si algo no responde, mira primero `docker compose -f deploy/dev/compose.yaml ps`. Si hay contenedores caídos, ejecuta `make dev` otra vez.

## Anexo B · Pedir un token a mano (sin la colección)

Sirve para entender qué hace el script o para depurar:

```bash
curl -X POST "https://id.34-134-21-66.sslip.io/realms/argos/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=argos-tests -d scope=openid \
  -d username=dpo.test -d "password=<contraseña>" -d totp=<código de 6 dígitos>
```

La respuesta trae `access_token` y `expires_in` (300 s). Con él:

```bash
curl -H "Authorization: Bearer <access_token>" "https://api.34-134-21-66.sslip.io/api/v1/campaigns?limit=4"
```

No dejes contraseñas en el historial de la consola: en Git Bash puedes empezar la línea con un espacio si tienes `HISTCONTROL=ignorespace`.
