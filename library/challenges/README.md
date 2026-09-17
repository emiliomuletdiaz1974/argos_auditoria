# Biblioteca de retos de ARGOS

Un **reto** es una pregunta formal con criterio de conformidad: qué se sondea, sobre qué activos, con
qué criterio se decide y qué evidencia se captura. El formato lo fija
[`schema/challenge.schema.json`](schema/challenge.schema.json) (ARG-041) y se puede escribir en
castellano: la capa de traducción lo lleva al núcleo en inglés (ADR-0007).

## Familias

| Prefijo | Familia | Qué verifica |
|---|---|---|
| `acc-` | accesos | quién puede leer qué |
| `brc-` | brechas | registro y notificación de brechas |
| `coh-` | coherencia | lo declarado frente al inventario (delegan en SHACL o en consultas del inventario) |
| `doc-` | documentación | documentos que la norma exige |
| `ds-` | espacios de datos | condiciones ODRL de un activo compartido |
| `dsr-` | derechos | acceso, supresión y demás derechos del interesado |
| `ret-` | conservación | plazos frente al calendario declarado |
| `sec-` | seguridad | medidas técnicas: cifrado, registro de accesos |

Los retos específicos de un sector viven en subcarpetas por vertical dentro de su familia.

## Ciclo de vida

1. **Alta:** se escribe el YAML en la carpeta de su familia y pasa `make challenge-lint` (esquema y
   reglas del producto) y la matriz de trazabilidad de la ontología.
2. **Catálogo:** `uv run python tools/challenge_catalog.py` genera `catalog.yaml` desde los retos.
   **No se edita a mano**; `--check` comprueba que está al día. Un id que las poblaciones ya citan
   pero cuyo reto aún no existe aparece con `draft: true`.
3. **Publicación:** `tools/ontology_publish.py build` congela los retos en `archive/<versión>/` y los
   empaqueta, junto con la ontología, en el bundle firmado (ARG-040).
4. **Archivo:** una versión archivada no cambia. La verificación de una subsanación usa la versión
   que midió el problema (ARG-049).

## Versionado de un reto

- **Parche** (`1.0` → `1.1`): corrige la sonda sin cambiar el criterio.
- **Menor** (`1.1` → `1.2`): amplía conectores o endurece un parámetro sin cambiar qué se decide.
- **Mayor** (`1.x` → `2.0`): cambia el criterio o la evidencia. El anterior queda archivado y los
  hallazgos abiertos se verifican con él.
