---
id: FASE-08
kind: phase
title: Fase 08 · Consola y APIs
phase: "08"
version: 0.1.0-alpha
commit: 44c1785
date: 2026-09-22
status: current
confidentiality: client
---

# Fase 08 · Consola y APIs

> **Una puerta y una pantalla.** Todo lo que ARGOS enseña o deja hacer pasa ahora por una sola API autenticada y por una consola servida desde el mismo contenedor. Lo que la consola puede hacer, una integración del cliente puede hacerlo igual: no hay rutas privadas. El asistente es la única pieza que depende del modelo local (F06-05); sin él responde `503` y la consola lo dice en vez de disimular.

## 1. Resumen

La Fase 08 pone cara a lo construido en las fases anteriores. La API única v1 sirve inventario, campañas, hallazgos, evidencia, credenciales, asistente y webhooks con un mismo contrato: errores RFC 9457, paginación por cursor opaco, idempotencia declarada y un asiento en el diario por cada mutación, con la persona detrás. Una matriz de autorización versionada decide quién puede qué, negando por defecto y separando deberes: quien lanza una campaña no aprueba sus compuertas ni cierra sus hallazgos.

La consola recorre el ciclo entero del cliente —ver el inventario, planificar una campaña y leer su plan antes de que corra nada, aprobar la compuerta, triar los hallazgos, subsanar, verificar la subsanación, descargar el expediente y emitir la credencial— sin inventarse reglas: la máquina de estados vive en el dominio y la interfaz solo ofrece lo que la API declara. Lo que no se puede hacer, no aparece: no hay ningún botón que cierre un hallazgo a mano.

## 2. Alcance

- **Incluido:** ARG-071 a ARG-080. Contrato OpenAPI v1 generado del código y su suite; matriz de autorización y separación de deberes; núcleo de la API (errores, paginación, idempotencia, auditoría); recursos de sistemas e inventario, campañas y compuertas, hallazgos y remediación verificada, evidencia y credenciales, asistente y webhooks firmados; consola completa con su sistema de diseño y su sesión PKCE; guion de la consola con Playwright y accesibilidad; contenedor único de API y consola, y retirada de `challenge-api`.
- **Fuera:** la prueba con un usuario de negocio sin acompañamiento (F08-98, la hace una persona); el modelo local (F06-05) del que depende el asistente; el endurecimiento de la plataforma (Fase 09) y la operación y el despliegue (Fase 10).

## 3. Entregables

| Módulo | Documento | Versión |
|---|---|---|
| argos-api | `modulos/argos-api.md` | 0.15.0-alpha |
| argos-console | `modulos/argos-console.md` | 0.8.0-alpha |
| argos-challenge-engine (ampliado) | `modulos/argos-challenge-engine.md` | 0.1.0-alpha |
| argos-evidence (ampliado) | `modulos/argos-evidence.md` | 0.13.0-alpha |
| argos-ai-gateway (ampliado) | `modulos/argos-ai-gateway.md` | 0.1.0-alpha |

## 4. Prueba de la fase

Criterio del Plan Director §8.2: el recorrido completo por la consola termina con el hallazgo cerrado por la reejecución; la API v1 pasa su suite de contrato; el linter de color rechaza el uso indebido plantado; la matriz de autorización pasa entera y cada mutación deja su asiento en el diario.

Se ejecutó con `make dev` (fuentes simuladas, Temporal, Keycloak, Vault, almacén WORM y los contenedores de la API con la consola, del gateway de IA y de los webhooks), sobre datos exclusivamente sintéticos, en `tests/e2e/test_phase8_acceptance.py`, más el guion de Playwright (`make console-e2e`) y la suite de contrato.

Resultado, 2026-09-22: todos los criterios en verde.

1. **Una sola procedencia:** el contenedor sirve la consola y la v1; la página no trae nada de un CDN y la v1 no responde nada sin un token del realm. El contrato que sirve es el que generó los tipos de la consola.
2. **La matriz manda y no concede nada por defecto:** lo que la API aplica coincide con la expectativa escrita a mano, un permiso no declarado no se puede ni pedir, y el auditor solo lee.
3. **Cada mutación queda en el diario** con su actor; una lectura no deja nada.
4. **Nadie cierra un hallazgo a mano:** la API responde `409`, el dominio rechaza a cualquier actor `user:`, y solo la reejecución —con actor `system:`— lo lleva a cerrado. El guion de la consola lo recorre de punta a punta y termina exactamente ahí.
5. **La regla de oro:** el dorado solo aparece en `accredited.css`, con un uso indebido plantado que la suite de la consola hace fallar.
6. **Accesibilidad:** contraste AA de todos los pares de la paleta y foco visible en todo elemento interactivo de las cuatro pantallas.

## 5. Decisiones y desviaciones

- **ADR-0012 · API única.** Una sola puerta autenticada para el dominio; el documento DID, las listas de estado y el comprobador público se quedan en sus servicios. `challenge-api` se retiró en F08-17 con sus rutas ya cubiertas y sus tests migrados.
- **ADR-0013 · Consola.** React con `npm` y fichero de bloqueo, nunca un CDN; el token de acceso vive en memoria y el de refresco en una cookie HttpOnly que solo ve `/api/v1/auth/refresh`; los colores solo en los tokens.
- **Nota ARG-071-080.** Identificadores en inglés y sin `INSERT` propios: la API llama al dominio, no escribe en las tablas de otras fases.
- **Separación de deberes (ARG-072):** emitir la credencial pasó a `dpo_reviewer` y las integraciones (webhooks) son solo de `platform_admin`.
- **Pausa acotada (F08-17):** el puente del bus traduce el cortacircuitos del conector en la pausa de la campaña; como nadie envía el cierre, la pausa caduca con el mismo enfriamiento que usa el conector (300 s).

## 6. Interfaces que exporta

`docs/fases/interfaces-F08.md`. Lo que consumen las fases siguientes: la Fase 09 endurece esta misma puerta (TLS, cabeceras, límites, revisión de la matriz) y la Fase 10 la despliega y la opera, incluida la purga de la tabla de idempotencia.

## 7. Pendientes al cierre

- **Prueba con un usuario de negocio sin acompañamiento** (F08-98): la hace una persona con el guion de la consola; es el criterio que falta del Plan Director para esta fase.
- **`GET /api/v1/approvals` responde `501`:** la bandeja de lo que una persona tiene pendiente de aprobar en todas sus campañas está en el contrato y en la matriz, pero sin implementar. La consola no la usa: las compuertas se aprueban desde cada campaña (`/campaigns/{id}/gates`).
- **Asistente sin modelo local** (F06-05): el chat funciona contra el gateway, pero hasta que estén los pesos responde `503` y la consola lo declara.
- **Purga de `argos.api_idempotency`** (Fase 10): la tabla guarda la respuesta de cada mutación con clave de idempotencia y todavía nadie la limpia.
- **Cableado que espera a la Fase 10:** el registro del cliente `argos-console` en el realm está en el compose de desarrollo; el despliegue real (dominios, TLS y secretos) es de operación.
- **El guion de Playwright corre contra un aparato de mentira** (`console/e2e/server.mjs`), no contra la API real: comprueba la consola, no el backend. El backend lo cubren la suite de contrato y los tests de integración.
