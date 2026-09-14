# ADR-0001 · Alcance de la Fase 1 y estructura del monorepo

**Estado:** Aceptado · 2026-09-14 · Aaron Escobar

## Contexto
El Plan Director (ARGOS-CTO-2026-001 §8.2) describe la Fase 1 como librería común (configuración, logging, errores, diario), gestor de secretos local, compose de desarrollo, `/salud` y CI. El documento ARGOS_Fase01 numera ARG-001…010 como monorepo, imagen Packer, k3s, PostgreSQL+AGE+pgvector, esquema núcleo, NATS, Temporal, Keycloak, Vault y CI con cosign. Las estructuras de repositorio también difieren: `services/conectores/…` (Plan) frente a `connectors/`, `services/<servicio-en-inglés>/`, `platform/`, `library/` (ARG-001). El código existente en `argos/` ya sigue la estructura de ARG-001.

## Decisión
1. Los documentos de fase mandan en **numeración, contenido de componentes y rutas**. El Plan Director manda en **orden de construcción, método, calendario y definición de hecho**.
2. Estructura del monorepo: la de ARG-001 más lo que el Plan añade:
   `libs/comun/` (librería común), `services/`, `connectors/`, `console/`, `platform/`, `library/`, `tools/`, `deploy/dev/` (compose de desarrollo), `tests/` (integración y extremo a extremo), `docs/{adr,desviaciones,fases,plantillas}`.
3. La librería común (configuración, errores, logging, diario v1) se registra como parte de ARG-001 (convenciones) y ARG-005 (diario).
4. **ARG-002 (imagen Packer) y ARG-003 (k3s) se aplazan** hasta tener el Servidor Cognitivo de laboratorio. Mientras, el entorno es Docker Compose con los mismos servicios. Se abre Nota de Desviación ARG-002/003.

## Consecuencias
- El código de referencia de los documentos se puede transcribir con sus rutas sin traducirlas.
- La F1 queda cerrable sin hardware; la prueba de fase de ARG-002/003 se traslada a F10 (instalador) o a la llegada del hardware.

## Alternativas descartadas
- Estructura del Plan Director en castellano: obligaría a reescribir las rutas de los 100 componentes y a mantener dos nomenclaturas.
- Construir Packer y k3s ya: sin hardware no hay prueba real de arranque medido ni de drivers GPU.
