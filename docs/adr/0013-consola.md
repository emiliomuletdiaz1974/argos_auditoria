# ADR-0013 · La consola: herramientas, pruebas y cómo se sirve

- **Estado:** Propuesta
- **Fecha:** 2026-09-20
- **Decide:** el usuario (tarea F08-00)
- **Contexto:** Fase 08 · Consola y APIs (ARG-073…ARG-080) · Pliego P-03 y P-18 · Plan Director §9.3

## Contexto

El documento de la Fase 08 fija el marco de trabajo del frontend —**React**, servido como estáticos desde el propio appliance, sin CDN (P-03)— y el Plan Director §9.3 dice que el marco que fija el documento se respeta. Lo que el documento no fija es el resto de la cadena: empaquetador, lenguaje, pruebas y cómo llegan los estáticos al appliance. Es la primera vez que este repositorio tiene código que no es Python, así que conviene decidirlo entero y de una vez.

## Decisión propuesta

1. **React con Vite y TypeScript en modo estricto.** El documento escribe los ejemplos en `.jsx`; se respetan las decisiones de producto (SWR para datos, tokens CSS, estructura de vistas) y se traducen a `.tsx`. Motivo: en este repositorio el tipado estricto es una regla de casa (`mypy --strict` en todo el Python) y la consola consume un contrato OpenAPI del que se pueden **generar los tipos**, de modo que un cambio en la API rompe la compilación de la consola en vez de romperse en la cara del DPO.
2. **Tipos generados del contrato.** `openapi-typescript` produce `console/src/api/schema.d.ts` desde `services/api/openapi.json`; el CI comprueba que está al día, como con el catálogo de retos.
3. **Pruebas en tres niveles:** Vitest y Testing Library para los componentes con decisiones (cola de revisión, plan previo, detalle de hallazgo, modal de aceptación de riesgo, cadena de evidencia); **Playwright** para el guion completo «de la campaña al cierre verificado de un hallazgo», que es la prueba de la fase; y `stylelint` para la regla del dorado (ARG-080), con un uso indebido plantado que el CI debe rechazar.
4. **npm como gestor**, con `package-lock.json` versionado y `npm ci` en el CI: instalación reproducible, sin descargas sorpresa.
5. **La consola se sirve desde la API única.** `npm run build` deja los estáticos en `console/dist`; la imagen de `argos-api` los copia y FastAPI los sirve en `/` (la API vive bajo `/api/v1`). Un solo contenedor, un solo origen, sin CDN ni servidor extra.
6. **Sesión OIDC con PKCE** contra el Keycloak del appliance (cliente público `argos-console`): token de acceso solo en memoria, refresco en cookie `HttpOnly`, `Secure` y `SameSite=Strict` que solo ve `/api/v1/auth/refresh`.
7. **Accesibilidad como requisito, no como intención:** contraste AA verificado sobre los pares de la paleta y foco visible en todo elemento interactivo, ambos comprobados en las pruebas de componentes.

## Consecuencias

- El repositorio pasa a tener dos cadenas de herramientas. `make check` incorpora `console-lint`, `console-test` y la comprobación de tipos generados; el entorno de desarrollo necesita Node (hay v26 en la máquina de trabajo) y el CI, un paso de `setup-node`.
- Playwright descarga navegadores la primera vez: en el CI se cachean, y en local es una orden explícita (`make console-e2e-setup`), nunca automática.
- Generar los tipos del contrato ata la consola a la API: es justo lo que se busca.

## Alternativas descartadas

- **JSX sin tipos, como en el documento:** más fiel al ejemplo, pero renuncia a que el contrato rompa la compilación; con una API que cambia cada fase, es renunciar a la red de seguridad.
- **Next.js u otro marco con servidor:** el appliance sirve estáticos; un servidor de frontend es otra pieza que operar y endurecer.
- **CDN para las dependencias:** prohibido por P-03 (el appliance funciona aislado).
- **Cypress en lugar de Playwright:** Playwright trae navegadores en el mismo paquete y corre sin servidor gráfico; encaja mejor en un CI sin pantalla.
