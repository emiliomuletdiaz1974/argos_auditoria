---
id: MOD-argos-console
kind: module
title: Consola de ARGOS (argos-console)
module: argos-console
phases: ["08"]
version: 0.3.0-alpha
commit: pendiente
date: 2026-09-21
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

- Ningún token de acceso en `localStorage` ni en `sessionStorage`: lo comprueba una prueba que revisa todo lo guardado tras iniciar sesión y tras renovar.
- El refresco nunca llega al JavaScript de la página: viaja solo en la cookie `HttpOnly`.
- Una vuelta de Keycloak con un `state` que la consola no envió se rechaza.
- Sin dependencias servidas desde una CDN: todo va en el paquete que sirve el appliance.

## 7. Operación

En desarrollo: `make console-install` y `npm --prefix console run dev` (Vite hace de proxy de `/api` hacia la API en `127.0.0.1:8009`). `make console-build` deja los estáticos en `console/dist`.

## 8. Verificación

- `src/auth/pkce.test.ts`: longitud y alfabeto del verificador; reto S256 igual al de otra implementación (`node:crypto`).
- `src/auth/session.test.ts`: redirección con reto S256 y sin el verificador, token solo en memoria, `state` ajeno rechazado, renovación y su fallo.
- `src/api/client.test.ts`: el token viaja; un `401` renueva y reintenta una vez; sin bucles.
- `src/styles/design.test.ts`: el uso indebido del dorado **plantado** falla, el dorado permitido pasa, ningún componente declara un color, la paleta es la de la marca y todos sus pares de texto llegan a AA.
- `src/views/inventory/inventory.test.tsx`: la cobertura es el número grande y lo especial va en ámbar (nunca en dorado); el nodo trae procedencia, vecindario enlazado y línea temporal; `404` explicado; la cola confirma y corrige enviando lo que espera la API; todas las acciones son botones reales alcanzables con el teclado.
- `src/views/campaigns/campaigns.test.tsx`: plan agrupado con las preguntas literales y lo no verificable aparte, `409` explicado, compuerta con doble control y aprobación, progreso con pausas y su motivo, y expediente descargable solo al sellar.
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
