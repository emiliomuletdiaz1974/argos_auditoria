# ARGOS · orquestación del monorepo (ARG-001).
# Las recetas son órdenes simples que funcionan igual con sh (CI) y con cmd (Windows):
# no se fija SHELL porque en Windows "bash" puede resolver al lanzador de WSL.
COMPOSE := docker compose -f deploy/dev/compose.yaml

.PHONY: help dev dev-down lint tipos secretos test check cover

help:
	@echo "make dev       levanta el entorno de desarrollo (docker)"
	@echo "make dev-down  lo detiene"
	@echo "make test      tests unitarios"
	@echo "make check     lint + tipos + secretos + todos los tests (necesita make dev)"
	@echo "make cover     todos los tests con umbral de cobertura (necesita make dev)"

dev:
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root vault sh -s < deploy/dev/vault/setup.sh
	uv run --env-file .env.ejemplo python tools/migrate.py

dev-down:
	$(COMPOSE) down

lint:
	uv run ruff check .
	uv run ruff format --check .

tipos:
	uv run mypy libs

secretos:
	gitleaks detect --no-banner --redact

test:
	uv run pytest -m "not integracion"

check: lint tipos secretos
	uv run pytest

cover:
	uv run pytest --cov=argos_comun --cov-report=term-missing --cov-fail-under=80
