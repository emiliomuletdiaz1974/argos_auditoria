# ═══════════════════════════════════════════════════════════════════════════
# ARGOS Platform · Monorepo Makefile (Componente ARG-001)
# ═══════════════════════════════════════════════════════════════════════════

VERSION := $(shell cat VERSION)

.PHONY: help test lint format run-tests

help:
	@echo "Comandos disponibles:"
	@echo "  make test      - Ejecutar suite de pruebas unitarias con pytest"
	@echo "  make lint      - Ejecutar comprobación de sintaxis y tipos"

test:
	python -m pytest tests/

lint:
	python -m ruff check .
