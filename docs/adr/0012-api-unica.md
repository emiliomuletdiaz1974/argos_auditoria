# ADR-0012 · La API única v1 y qué pasa con las APIs que ya existen

- **Estado:** Aceptado
- **Fecha:** 2026-09-20
- **Decide:** el usuario (tarea F08-00) · **Aprobado:** 2026-09-20
- **Contexto:** Fase 08 · Consola y APIs (ARG-071, ARG-072) · Pliego P-18, P-19, P-20 · Especificación Técnica §3.7

## Contexto

El documento de la Fase 08 es tajante: «no hay endpoints privados de la consola, porque un producto de evidencia no puede tener dos verdades». Pero ARGOS ya tiene APIs en marcha, nacidas cada una en su fase:

| Servicio | Puerto | Qué expone | Quién lo usa |
|---|---|---|---|
| `challenge-api` | 8003 | Campañas, compuertas, hallazgos, sujeto sintético, subsanación (ARG-047) | Integraciones y tests |
| `inventory` (GraphQL) | — | Selector y navegación del grafo (ARG-029) | Ontología, motor de retos |
| `ai-gateway` | 8005 | Clasificación, RAG, asistente (ARG-052…058) | Solo dentro del perímetro de IA |
| `evidence-api` | 8008 | Documento DID, listas de estado y credenciales (ARG-068) | **Cualquiera**, sin autenticación |
| `verifier` | 8007 | Comprobador público (ARG-069) | Terceros |

La pregunta no es si hacemos la API única, sino qué ocurre con estas.

## Decisión

1. **Una sola API autenticada: `argos-api` (`services/api`, paquete `argos_api`), bajo `/api/v1`.** Es la que usan la consola y el cliente; no hay rutas reservadas a la consola. Reúne los recursos del dominio: `systems`, `inventory`, `campaigns`, `findings`, `evidence`, `credentials`, `assistant`, `approvals` y `webhooks`.
2. **La API llama a las librerías del dominio, no a otros servicios**, igual que hace hoy la API de campañas: mismo proceso, mismos módulos (`argos_challenges`, `argos_inventory`, `argos_evidence`). La excepción es el **gateway de IA**, al que llama por HTTP porque vive en su propia red y ese aislamiento es un requisito de la Fase 06.
3. **`challenge-api` se retira** cuando la API única cubra sus rutas: sus endpoints se reescriben como routers de `argos_api` y su contenedor desaparece del `compose`. No mantenemos dos puertas al mismo dominio.
4. **`evidence-api` y `verifier` se quedan.** Publican material que debe ser accesible **sin credenciales** (documento DID, listas de estado, credenciales, comprobación de un tercero). Mezclarlo con la API autenticada obligaría a abrir rutas públicas dentro de ella.
5. **El grafo se sigue consultando con GraphQL** (ARG-029): una API REST no es la herramienta para navegar un vecindario de grafo a profundidad variable. La consola no habla con él directamente: la API única lo monta bajo `/api/v1/inventory/graph`, con la misma autenticación y la misma matriz de permisos. El resto del inventario (cobertura, catálogo, cola de revisión) es REST.
6. **Decisiones transversales, como fija el documento:** paginación por cursor opaco, errores `application/problem+json` (RFC 9457), `Idempotency-Key` en todo POST que crea, versión `v1` en la ruta y contrato OpenAPI **generado del código**, publicado por el propio appliance y comprobado en CI contra el fichero versionado (`services/api/openapi.json`): si el código y el contrato divergen, el CI falla.
7. **Toda mutación deja asiento en el diario** (P-19) desde un middleware, con actor, recurso y resultado; un test por endpoint mutador lo comprueba.

## Consecuencias

- Un solo sitio donde mirar el contrato, y un solo sitio donde está la autorización.
- Retirar `challenge-api` obliga a mover sus tests de integración a la API única; se hace en la misma tarea, no después.
- La consola necesita dos orígenes (la API única y, para verificar, el comprobador público); es explícito en la configuración.
- Las rutas públicas de `evidence-api` quedan fuera de la matriz de permisos **a propósito**: lo que sirven es material que cualquiera debe poder comprobar.

## Alternativas descartadas

- **Una API por servicio, con la consola llamando a cada una:** dos verdades y dos autorizaciones; lo que el documento prohíbe.
- **Pasarela que reenvía por HTTP a los servicios actuales:** una capa más, latencia y dos despliegues para cada cambio, sin ganar aislamiento (salvo en la IA, donde sí lo mantenemos).
- **GraphQL para todo:** el cliente integra por REST (el pliego habla de integración con su GRC) y la suite de contrato REST es la que se le entrega.
