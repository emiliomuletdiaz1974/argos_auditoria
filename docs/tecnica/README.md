# Documentación técnica de ARGOS

Documentación por módulo y por fase cerrada, preparada para entregarse a clientes. Cada documento lleva una cabecera con su versión, el commit que lo deja al día y su confidencialidad (`client` o `internal`).

- **Plantillas:** [módulo](plantillas/modulo.md) · [cierre de fase](plantillas/cierre-fase.md)
- **Comprobar que no falta nada:** `make docs-check`
- **Paquete para un cliente** (Markdown, PDF, índice y manifiesto con SHA-256 en `dist/documentacion/`):
  `uv run python tools/docs_pack.py --phase 03 --label <cliente>`, o `--module <paquete>`, o `--all`; `--include-internal` solo con autorización.

## Fases

| Fase | Documento | Estado |
|---|---|---|

## Módulos

| Paquete | Documento | Fases |
|---|---|---|
