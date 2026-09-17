# Documentación técnica de ARGOS

Documentación por módulo y por fase cerrada, preparada para entregarse a clientes. Cada documento lleva una cabecera con su versión, el commit que lo deja al día y su confidencialidad (`client` o `internal`).

- **Plantillas:** [módulo](plantillas/modulo.md) · [cierre de fase](plantillas/cierre-fase.md)
- **Comprobar que no falta nada:** `make docs-check`
- **Paquete para un cliente** (Markdown, PDF, índice y manifiesto con SHA-256 en `dist/documentacion/`):
  `uv run python tools/docs_pack.py --phase 03 --label <cliente>`, o `--module <paquete>`, o `--all`; `--include-internal` solo con autorización.

## Fases

| Fase | Documento | Estado |
|---|---|---|
| 01 · Cimientos de la plataforma | [F01-cimientos.md](fases/F01-cimientos.md) | Cerrada (`fase-01`) |
| 02 · Conectores de solo lectura | [F02-conectores.md](fases/F02-conectores.md) | Cerrada (`fase-02`) |
| 03 · Inventario y grafo de conocimiento | [F03-inventario-grafo.md](fases/F03-inventario-grafo.md) | Cerrada (`fase-03`) |
| 04 · Ontología normativa | [F04-ontologia-normativa.md](fases/F04-ontologia-normativa.md) | Cierre técnico (`fase-04-tecnica`); contenido pendiente de validación jurídica |

## Módulos

| Paquete | Documento | Fases |
|---|---|---|
| `argos-auth` | [argos-auth.md](modulos/argos-auth.md) | 01 |
| `argos-challenge-engine` | [argos-challenge-engine.md](modulos/argos-challenge-engine.md) | 01 (base; completo en 05) |
| `argos-common` | [argos-common.md](modulos/argos-common.md) | 01, 03 |
| `argos-connector-dicom` | [argos-connector-dicom.md](modulos/argos-connector-dicom.md) | 02 |
| `argos-connector-fhir` | [argos-connector-fhir.md](modulos/argos-connector-fhir.md) | 02 |
| `argos-connector-files` | [argos-connector-files.md](modulos/argos-connector-files.md) | 02 |
| `argos-connector-ldap` | [argos-connector-ldap.md](modulos/argos-connector-ldap.md) | 02 |
| `argos-connector-rest` | [argos-connector-rest.md](modulos/argos-connector-rest.md) | 02 |
| `argos-connector-sdk` | [argos-connector-sdk.md](modulos/argos-connector-sdk.md) | 02, 03 |
| `argos-connector-sql` | [argos-connector-sql.md](modulos/argos-connector-sql.md) | 02, 03 |
| `argos-events` | [argos-events.md](modulos/argos-events.md) | 01 |
| `argos-example` | [argos-example.md](modulos/argos-example.md) | 01 (interno) |
| `argos-inventory` | [argos-inventory.md](modulos/argos-inventory.md) | 03, 04 |
| `argos-ontology` | [argos-ontology.md](modulos/argos-ontology.md) | 04 |
