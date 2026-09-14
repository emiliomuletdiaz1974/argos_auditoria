# ADR-0005 · Idioma del código

**Estado:** Aceptado · 2026-09-14 · Aaron Escobar

## Contexto
Hasta F1-06 el código de `argos/` usó identificadores, comentarios y mensajes en español, siguiendo el idioma de la documentación de negocio. El esquema SQL y el código de referencia de los documentos de fase ya estaban en inglés, así que convivían dos idiomas.

## Decisión
- **Todo lo que es código va en inglés:** identificadores, nombres de archivo, carpeta y paquete, comentarios, docstrings, mensajes de log y de error, nombres de tests, claves JSON, endpoints y valores enumerados de base de datos.
- **La documentación y git siguen en español:** ADR, notas de desviación, README, planes, mensajes de commit y nombres de rama.
- **Alcance:** `argos/`. `argos-web/` es código heredado y se mantiene como está.
- **Correspondencia de nombres:** los documentos de fase se leen como especificación y se implementan con los nombres en inglés que fija el glosario del equipo.

## Consecuencias
- Refactor único del código existente y reescritura de los planes pendientes.
- Cambia la migración `0001` (valores de `campaigns.status`, mensajes): la base de desarrollo se recrea; no hay entornos desplegados afectados.
- Los endpoints del servicio de ejemplo pasan a `/health`, `/health/live`, `/demo/entries` y `/journal/verification`.
- La fórmula del diario v1 (ADR-0002) no cambia: sus etiquetas de dominio ya estaban en inglés y los vectores de prueba conservan los mismos hashes.

## Alternativas descartadas
- **Solo identificadores en inglés y comentarios en español:** mezcla idiomas dentro del mismo archivo.
- **Migrar solo el código nuevo:** dejaría dos convenciones en el mismo repositorio durante meses.
