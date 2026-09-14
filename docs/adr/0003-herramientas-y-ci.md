# ADR-0003 · Herramientas de desarrollo y CI

**Estado:** Propuesta · **Fecha:** 2026-09-14

## Contexto
ARG-001/ARG-010 usan uv y GitLab CI autoalojado con cosign y clave en Vault. El Plan Director usa GitHub (repo, Projects, rama protegida). Hoy `argos/` usa pip, no tiene lockfile y ruff no está instalado.

## Decisión
- Python 3.12, **uv** con workspace y `uv.lock` versionado.
- **ruff** (lint y formato, línea 100), **mypy** estricto en `libs/` y en cada servicio, **pytest** con `pytest-cov`, **gitleaks** en local y en CI.
- `make dev | test | check | cover` como interfaz única; en CI se llama a los mismos objetivos.
- **CI en GitHub Actions** sobre el repo privado `argos-platform`, con las etapas de ARG-010: `verify`, `build`, `package`, `sign`, `selfcheck`. Hasta que exista Vault de release (F1-10), `sign` y `selfcheck` quedan declarados y marcados como reservados. Runner alojado por GitHub hasta tener el autoalojado.
- Tests de integración marcados `@pytest.mark.integracion`; `make test` ejecuta unitarios; `make check` añade integración contra `make dev`.

## Consecuencias
- Nota de Desviación ARG-010 (GitLab → GitHub Actions; misma estructura de etapas).
- Se mantiene la portabilidad a un runner autoalojado sin nubes (requisito del documento).

## Alternativas descartadas
- GitLab autoalojado ya: añade infraestructura que operar antes de tener código.
- pip + requirements: no ofrece lockfile reproducible por componente.
