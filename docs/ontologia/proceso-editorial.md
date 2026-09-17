# Proceso editorial de la ontología normativa

**Componente:** ARG-038 · **ADR:** 0006 · **Compromiso:** SLA interno de **30 días naturales** desde la publicación oficial de una norma o de su modificación hasta que sus obligaciones están publicadas en un bundle firmado, con reto o con motivo de verificación pendiente.

## Roles

| Rol | Responsabilidad |
|---|---|
| **Jurista** (perfil jurídico-técnico) | Redacta la obligación en la plantilla editorial en castellano: norma, artículo, título, vigencia, severidad y resumen verificable. Aprueba el contenido. |
| **Ingeniero normativo** | Formaliza: clases de activo, retos del catálogo, equivalencias y declaración de la norma y sus artículos. Aprueba la formalización. |
| **Revisor** | Segunda persona que revisa el pull request, distinta de las dos anteriores cuando el equipo lo permite. |

Ninguna obligación entra en una publicación sin la aprobación del jurista y del ingeniero normativo en el pull request.

## Etapas y plazos

El día 0 es la fecha de publicación en el DOUE o en el BOE.

| Día límite | Etapa | Resultado verificable |
|---|---|---|
| D+3 | **Detección y alcance.** El observatorio normativo registra la norma; el jurista decide si entra en el paquete y qué artículos son verificables. | Rama `feature/poblacion-<norma>` con la lista de artículos. |
| D+10 | **Redacción.** El jurista rellena una plantilla `library/ontology/editorial/<OBL-ID>.yaml` por obligación. | Plantillas en la rama. |
| D+15 | **Formalización.** El ingeniero normativo declara la norma y sus artículos en `library/ontology/norms/<NORMA>.ttl`, enlaza clases de activo y retos, y compila con `tools/ontology_compile.py`. | Turtle generado y catálogo actualizado. |
| D+18 | **Puertas.** `make ontology-gates` pasa las cinco puertas (sintaxis, consistencia, cobertura, trazabilidad y firma en seco) en local y en CI. | Pull request en verde. |
| D+23 | **Validación jurídica.** El jurista aprueba cada obligación y queda el registro `docs/validaciones/<NORMA>-vN.md`. | Registro de validación firmado por nombre y rol. |
| D+27 | **Retos.** Cada obligación tiene su reto implementado en la biblioteca de retos o un `pendiente_verificacion` con motivo explícito; nunca las dos cosas ni ninguna. | Matriz de trazabilidad sin errores. |
| D+30 | **Publicación.** `tools/ontology_publish.py` construye y firma el bundle con `argos-content`; se publican las matrices de trazabilidad y de solapamiento con la versión. | Bundle firmado, `traceability.*` y `overlap.*`. |

Si una etapa se retrasa, el plazo total no se amplía: la obligación afectada se publica con `pendiente_verificacion` y el motivo, y se completa en la siguiente versión.

## Reglas

- **Identificadores estables.** Un `OBL-…` o un id de reto publicados no se reutilizan con otro significado. Una obligación retirada se borra y su id no vuelve a usarse; una modificación sustancial es una obligación nueva con `supersedes`.
- **Vigencia por fecha de aplicación.** `vigente_desde` es la fecha en que la obligación es exigible según las disposiciones finales de la norma, no la de entrada en vigor.
- **Honestidad.** Lo que no se puede verificar técnicamente se publica como pendiente con su motivo; no se inventan retos para cubrir la matriz.
- **Solo contenido generado por herramienta.** `library/ontology/norms/generated/` se genera con `tools/ontology_compile.py`; nunca se edita a mano.
- **Verdad terreno.** Si un cambio altera qué aplica a la instantánea de demostración, se actualiza `tests/fixtures/applicability_ground_truth.yaml` y se valida de nuevo.

## Matriz de solapamiento

`uv run python tools/ontology_overlap.py --output dist` lista las clases de activo que reciben obligaciones de dos o más normas, con las equivalencias declaradas (`equivalencias` en la plantilla). Son los puntos en los que una sola campaña produce evidencia para varias normas. Se publica con cada versión junto a la matriz de trazabilidad; el jurista revisa que los solapamientos sean reales y propone las equivalencias con otros marcos (ENS, NIS2).
