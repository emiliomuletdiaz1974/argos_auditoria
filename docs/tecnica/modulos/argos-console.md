---
id: MOD-argos-console
kind: module
title: Consola de ARGOS (argos-console)
module: argos-console
phases: ["08"]
version: 0.13.0-alpha
commit: 34fc10a
date: 2026-09-24
status: current
confidentiality: client
---

# Consola de ARGOS (argos-console)

## 1. Propósito

Es la interfaz con la que el DPO, el responsable de campañas y el auditor trabajan con ARGOS. Habla solo con la API única v1 —no tiene rutas propias— y la sirve el propio appliance, sin CDN (pliego P-03). Implementa ARG-073 (sesión) y ARG-080 (sistema de diseño) según el ADR-0013.

## 2. Alcance y límites

- **Hace (F08-10):** el armazón —navegación, sesión OIDC con PKCE, cliente de la API con renovación— y el sistema de diseño con sus reglas comprobadas.
- **Vistas hechas:** inventario (F08-11) y campañas (F08-12).
- **No hace todavía:** las vistas de hallazgos, evidencia y asistente llegan con F08-13 a F08-15; el guion completo y la accesibilidad de extremo a extremo, con F08-16; servirla desde el contenedor de la API, con F08-17.
- **No hace nunca:** guardar un token de acceso fuera de la memoria, ni decidir nada que decida el servidor (las transiciones de un hallazgo, por ejemplo, las sirve la API).

## 3. Arquitectura

- React con Vite y TypeScript en modo estricto (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`). npm con `package-lock.json` y `npm ci`.
- `src/auth/pkce.ts`: verificador y reto S256 con la Web Crypto del navegador, sin librerías.
- `src/auth/session.ts`: `Session`. Envía a la persona al Keycloak del appliance con el reto; a la vuelta entrega código y verificador a `POST /api/v1/auth/session`, que responde con el token de acceso y deja el de refresco en una cookie `HttpOnly`, `Secure`, `SameSite=Strict` limitada a `/api/v1/auth/refresh`. El token de acceso vive solo en memoria; lo único que sobrevive a la redirección es el verificador y el `state`, y se borran al volver.
- `src/api/client.ts`: `createApiFetch`. Cada llamada lleva el token en memoria; un `401` renueva una sola vez y reintenta una sola vez. Un segundo `401` se devuelve tal cual: una sesión caducada nunca se convierte en un bucle.
- `src/api/context.tsx`: `ApiProvider`, `useResource` (SWR sobre la API v1) y `send` (mutaciones que devuelven el problema RFC 9457 como error legible).
- `src/views/inventory/`: `InventoryMap` (tarjeta por sistema con la cobertura como número grande, categoría especial en ámbar y nunca en dorado, nodos desaparecidos y pendientes), `NodeExplorer` (procedencia —conector, primera y última vez visto—, vecindario navegable y línea temporal de deltas) y `ReviewQueue` (confirmar, corregir a otra categoría o rechazar, en línea).
- `src/views/campaigns/`: `PlanPreview` (la lista literal de lo que se va a preguntar, agrupada por obligación, con lo no verificable en su sección y el aviso de que aún no se ha sondeado nada), `GateTray` (compuertas con su doble control: cuántas aprobaciones hay, de quién y que falta otra persona distinta), `LiveProgress` (progreso del workflow cada 5 s mientras corre, con los sistemas en pausa por cortacircuitos y su motivo) y `CampaignDetail` (descarga del expediente con el token en memoria cuando la campaña está sellada).
- `src/views/findings/`: `FindingsBoard` (peor primero en el orden que da la API, con filtros de severidad y estado que viven en la dirección y sobreviven a una recarga o a un enlace compartido), `FindingDetail` (el porqué completo —criterio, valor observado, declaración muestral, enlace al asiento del diario de la consulta y la obligación con su artículo—, solo las transiciones que trae `allowed_transitions`, la reejecución cuando el hallazgo espera verificación y su historia) y `AcceptRiskModal` (justificación de al menos 20 caracteres y caducidad obligatorias, con el aviso de que queda en el diario y en el expediente). No hay botón de cerrar: cerrar es lo que hace la reejecución si el reto pasa.
- `src/views/evidence/`: `EvidenceChain` (cada eslabón con su estado real: artefactos, raíz, firma —la de desarrollo dice que no vale fuera de las pruebas—, sello —en cola se dice en cola— y diario anclado; aquí nunca hay dorado), `ArtifactBrowser` (índice paginado y descarga de cada artefacto con su prueba de inclusión), `EvidenceDownloads` (expediente en JSON y PDF y paquete de verificación para un tercero), `IssueCredential` (tabla de cada campo que viaja con su valor, lista de lo que se queda en el expediente, confirmación explícita del revisor y relectura de la vista previa si el expediente cambió; solo una credencial acreditada lleva `credential-seal`) y `JournalEntry` (el asiento `#journal-<seq>` al que enlaza un hallazgo, con su acción, instante, hash y la consulta literal).
- `src/views/assistant/`: `AssistantView`, el chat del asistente. Cada `[n]` del texto es un botón que despliega su fuente, la herramienta de la que salió y, si es normativa, el fragmento recuperado. Bajo cada respuesta se listan las herramientas consultadas. Un rehúso se presenta como tal, con los fragmentos más cercanos, y una respuesta cortada por el presupuesto se marca como incompleta. El pie recuerda siempre que las respuestas no son veredictos de conformidad. Sin modelo local (`503`) o con el cupo agotado (`429`), el chat lo dice y sigue usable. La conversación vive solo en la pantalla: nada se guarda en el navegador.
- `e2e/`: el guion de la fase con Playwright. `server.mjs` levanta un aparato de mentira —una sola procedencia que sirve la consola construida, la API v1 y el inicio de sesión del realm— que conserva las dos reglas que el guion existe para demostrar: nada se mueve sin la llamada que hace la interfaz, y un hallazgo no se cierra a mano (`transition` rechaza `closed_compliant` y `reopened` con `409`; solo la reejecución lo cierra, y solo si el reto vuelve a pasar). Lo único que una prueba hace por su cuenta es `POST /api/v1/__reset`, que devuelve ese mundo al principio entre guiones.
- `src/api/schema.d.ts`: tipos **generados** del contrato `services/api/openapi.json` (`openapi-typescript`); un cambio en la API rompe la compilación de la consola.

### Sistema de diseño (ARG-080)

| Pieza | Regla |
|---|---|
| `src/styles/tokens.css` | Único archivo con colores: piel oscura (`--bg`, `--panel`, `--panel-2`, `--line`, `--text`, `--text-muted`), acción teal (`--accent`, `--accent-hi`, `--accent-strong`), texto sobre color (`--on-accent`, `--on-light`), severidades (`--sev-critical`, `--sev-high`, `--sev-medium`, `--sev-low`) y el dorado (`--gold`) |
| `src/styles/accredited.css` | Único sitio donde puede usarse `--gold`: el veredicto acreditado (`.chip-verdict`) y la credencial (`.credential-seal`). Cuando algo brilla dorado, está acreditado |
| `stylelint.config.mjs` | Prohíbe colores literales (hexadecimales, con nombre o `rgb()`/`hsl()`) fuera de los tokens, y el dorado fuera de `accredited.css` |
| Contraste | Todos los pares de texto de la paleta alcanzan WCAG AA (4,5:1), comprobado en las pruebas |

Los nombres del documento de fase (`--sev-critica`, `--verdict`…) pasan a inglés por el ADR-0005. Ningún color de marca cambia; para llegar a AA se añadió `--accent-strong` (el *hover* del botón), el chip de severidad alta lleva texto oscuro y el de severidad baja usa el gris como borde.

## 4. Interfaces

| Tipo | Nombre | Descripción |
|---|---|---|
| Clase | `Session(config, { fetch, navigate })` | `login()`, `completeLogin(url)`, `refresh()`, `accessToken()`, `logout()` |
| Función | `createApiFetch(session, fetch?)` | La única puerta de la consola a la API v1 |
| API usada | `POST /api/v1/auth/session`, `POST /api/v1/auth/refresh` | Rutas abiertas de la API (sin token todavía) |
| Órdenes | `make console-install`, `console-lint`, `console-test`, `console-types`, `console-build` | Las tres del medio forman parte de `make check` y del CI |

## 5. Configuración

`VITE_OIDC_ISSUER` (por defecto el realm `argos` del Keycloak de desarrollo) y `VITE_OIDC_CLIENT_ID` (por defecto `argos-console`). La URL de retorno es `<origen>/callback`.

## 6. Seguridad y tratamiento de datos

- **Esclusa** (F09-13, ARG-090): la sección «Esclusa» muestra el resultado de cada fichero que entra (importado o rechazado, motivo y SHA-256; «sin leer» cuando se rechazó sin abrirlo) y ofrece para la salida solo los tipos de la lista cerrada.
- **Soporte** (F09-11, ARG-088): la sección «Soporte» pide el paquete de diagnóstico y muestra la nota, el índice con la huella y cada fichero tal como saldrá. La descarga exige marcar que se ha leído, y envía la huella del índice mostrado: la API solo cifra ese índice.
- **Segundo factor bajo demanda** (F09-07):
  - Ante un `401` con `insufficient_user_authentication`, el cliente no renueva la sesión. `Session.requireSecondFactor()` guarda la página, que es una ruta y nunca un token, y vuelve a pedir el inicio de sesión con `prompt=login&acr_values=otp`.
  - Al volver, la consola lleva a la persona a esa página con un aviso para que repita la acción.
  - El guion e2e lo recorre al aprobar la compuerta.
- Ningún token de acceso en `localStorage` ni en `sessionStorage`: lo comprueba una prueba que revisa todo lo guardado tras iniciar sesión y tras renovar.
- El refresco nunca llega al JavaScript de la página: viaja solo en la cookie `HttpOnly`.
- Una vuelta de Keycloak con un `state` que la consola no envió se rechaza.
- Sin dependencias servidas desde una CDN: todo va en el paquete que sirve el appliance.
- **«Salir»** (F09-30, SEC-041): el botón del menú borra el token de la memoria y pide a la API que revoque el refresco y borre su cookie; al recargar, la consola pide entrar de nuevo. La cookie es de sesión, así que cerrar el navegador también cierra la sesión.
- **Política de contenidos** (F09-30, SEC-046): la consola se sirve con `default-src 'self'; frame-ancestors 'none'`. Lo permite porque no tiene nada en línea ni pide nada a otro origen: su único salto fuera es la navegación a Keycloak.
- Una cita del asistente con `detail` vacío no despliega ningún fragmento (F09-28, SEC-033): una cadena vacía está contenida en cualquier referencia y antes enlazaba la primera.

## 7. Operación

En desarrollo: `make console-install` y `npm --prefix console run dev` (Vite hace de proxy de `/api` hacia la API en `127.0.0.1:8009`). `make console-build` deja los estáticos en `console/dist`.

## 8. Verificación

- `src/auth/pkce.test.ts`: longitud y alfabeto del verificador; reto S256 igual al de otra implementación (`node:crypto`).
- `src/auth/session.test.ts`: redirección con reto S256 y sin el verificador, token solo en memoria, `state` ajeno rechazado, renovación y su fallo.
- `src/api/client.test.ts`: el token viaja; un `401` renueva y reintenta una vez; sin bucles.
- `src/styles/design.test.ts`: el uso indebido del dorado **plantado** falla, el dorado permitido pasa, ningún componente declara un color, la paleta es la de la marca y todos sus pares de texto llegan a AA.
- `src/views/inventory/inventory.test.tsx`: la cobertura es el número grande y lo especial va en ámbar (nunca en dorado); el nodo trae procedencia, vecindario enlazado y línea temporal; `404` explicado; la cola confirma y corrige enviando lo que espera la API; todas las acciones son botones reales alcanzables con el teclado.
- `src/views/campaigns/campaigns.test.tsx`: plan agrupado con las preguntas literales y lo no verificable aparte, `409` explicado, compuerta con doble control y aprobación, progreso con pausas y su motivo, y expediente descargable solo al sellar.
- `src/views/findings/findings.test.tsx`: orden de la API, filtros enviados y conservados en la dirección, porqué completo con el enlace al diario, transiciones exactamente las servidas, ausencia de cierre manual, reejecución como única salida de «pendiente de verificación», historia del reabierto y modal que exige justificación y caducidad.
- `src/views/evidence/evidence.test.tsx`: sello en cola y firma de desarrollo dichos tal cual, eslabones que faltan, sello concedido con su política, paginación y descarga con prueba de inclusión, tres descargas, vista previa de lo que viaja y lo que no, confirmación obligatoria, `409` que obliga a revisar de nuevo, dorado solo en la credencial acreditada y asiento del diario citado o rechazado.
- `src/views/assistant/assistant.test.tsx`: pregunta enviada, citas desplegables con fragmento y origen, herramientas visibles, rehúso con fragmentos cercanos, respuesta incompleta, aviso permanente en el pie y mensajes distintos sin modelo y sin cupo.
- `e2e/campaign-to-closed-finding.spec.ts`: entrar, leer el plan previo antes de que corra nada, aprobar la compuerta, seguir el progreso, triar el hallazgo, comprobar que no hay botón de cerrar, remediarlo, declararlo subsanado, lanzar la reejecución y verlo cerrado por `system:remediation`; al final, el asiento del diario enlazado, la cadena de evidencia y la credencial.
- `e2e/accessibility.spec.ts`: todo elemento interactivo de las cuatro pantallas se alcanza con el tabulador y marca el foco (contorno o sombra), y cada pantalla tiene un solo encabezado de nivel 1. El contraste AA de la paleta se comprueba en `src/styles/design.test.ts`.
- Se ejecuta con `make console-e2e`; el navegador se descarga a propósito con `make console-e2e-setup`, nunca solo. El CI lo corre en su propio job, con el navegador cacheado por la versión de Playwright. No entra en `make check`: `make check` no descarga navegadores.
- `tests/contract/test_api_session.py` (lado de la API): el código se convierte en token de acceso y en una cookie que la página no puede leer.

## 9. Limitaciones conocidas y pendientes

- Las vistas, el guion de Playwright y la comprobación de accesibilidad de extremo a extremo llegan con F08-11 a F08-16.
- El intercambio real de código contra Keycloak (`code_exchanger` de la API) se cablea con el contenedor en F08-17; hasta entonces la ruta de sesión responde `501`.
- Node 26 trae su propio `localStorage` global, que tapa el de jsdom; las pruebas se ejecutan con `--no-experimental-webstorage`.

## 10. Historial

| Versión | Fecha | Cambio | Tarea |
|---|---|---|---|
| 0.1.0-alpha | 2026-09-21 | Esqueleto de la consola: sesión OIDC con PKCE, cliente con renovación, sistema de diseño con la regla del dorado y tipos generados del contrato | F08-10 |
| 0.2.0-alpha | 2026-09-21 | Vista de inventario: mapa, explorador de nodos y cola de revisión con corrección | F08-11 |
| 0.3.0-alpha | 2026-09-21 | Vista de campañas: plan previo literal, bandeja de compuertas con doble control, progreso con pausas y expediente | F08-12 |
| 0.4.0-alpha | 2026-09-22 | Vista de hallazgos: tablero con filtros persistentes, detalle con el porqué completo y transiciones servidas por la API, reejecución, historia y modal de aceptación de riesgo; token `--overlay` | F08-13 |
| 0.5.0-alpha | 2026-09-22 | Vista de evidencia y credenciales: cadena con su estado real, artefactos con prueba de inclusión, descargas, emisión con vista previa y confirmación, y asiento del diario enlazado desde un hallazgo; `.actions` pasa a `app.css` | F08-14 |
| 0.6.0-alpha | 2026-09-22 | El chat del asistente: citas desplegables, herramientas visibles, rehúso con fragmentos cercanos, aviso permanente y avisos sin modelo o sin cupo | F08-15 |
| 0.7.0-alpha | 2026-09-22 | Guion completo con Playwright y pruebas de foco visible; arreglado el `fetch` sin enlazar que impedía iniciar sesión en un navegador real; el aviso de la reejecución sobrevive al cierre del hallazgo | F08-16 |
| 0.8.0-alpha | 2026-09-22 | La consola se construye dentro de la imagen de la API y se sirve desde su mismo origen; el realm acepta la vuelta a `http://127.0.0.1:8000/callback` | F08-17 |
| 0.9.0-alpha | 2026-09-23 | Una cita sin `detail` no se enlaza a ningún fragmento | F09-28 |
| 0.10.0-alpha | 2026-09-23 | Botón «Salir» que revoca la sesión, y consola servida con CSP estricta | F09-30 |
| 0.11.0-alpha | 2026-09-23 | Vuelta a iniciar sesión con segundo factor cuando la API lo pide | F09-07 (ARG-072) |
| 0.12.0-alpha | 2026-09-24 | Sección «Soporte»: revisión del paquete de diagnóstico antes de descargarlo | F09-11 (ARG-088) |
| 0.13.0-alpha | 2026-09-24 | Sección «Esclusa»: entrada verificada y salida de lista cerrada | F09-13 (ARG-090) |
