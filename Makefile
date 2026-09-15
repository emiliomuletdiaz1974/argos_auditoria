# ARGOS · monorepo orchestration (ARG-001).
# Recipes are plain commands that behave the same under sh (CI) and cmd (Windows):
# SHELL is not set because on Windows "bash" may resolve to the WSL launcher.
COMPOSE := docker compose -f deploy/dev/compose.yaml --profile sources
COMPOSE_HEAVY := docker compose -f deploy/dev/compose.yaml --profile sources --profile heavy
VERSION := $(strip $(file < VERSION))

.PHONY: help dev dev-heavy dev-down lint typecheck secrets test check check-heavy cover build manifest

help:
	@echo "make dev        start the development environment and simulated sources (docker)"
	@echo "make dev-heavy  also start SQL Server and Oracle (several GB of RAM)"
	@echo "make dev-down   stop it"
	@echo "make test       unit tests"
	@echo "make check      lint + typecheck + secrets + all tests (needs make dev)"
	@echo "make cover      all tests with coverage threshold (needs make dev)"
	@echo "make check-heavy tests that need make dev-heavy"
	@echo "make manifest   build images and write dist/release-manifest.json"

dev:
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root vault sh -s < deploy/dev/vault/setup.sh
	uv run --env-file .env.example python tools/migrate.py
	uv run --env-file .env.example python tools/register_dev_sources.py

dev-heavy: dev
	$(COMPOSE_HEAVY) up -d --wait
	$(COMPOSE_HEAVY) exec -T source-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P Dev-Only-Sa-2026 -i /init/01-erp.sql

dev-down:
	$(COMPOSE_HEAVY) down

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy libs services connectors

secrets:
	gitleaks detect --no-banner --redact

test:
	uv run pytest -m "not integration"

check: lint typecheck secrets
	uv run pytest -m "not heavy"

check-heavy:
	uv run pytest -m heavy

cover:
	uv run pytest -m "not heavy" --cov=argos_common --cov=argos_events --cov=argos_auth --cov=argos_connector --cov-report=term-missing --cov-fail-under=80

build:
	docker build -f services/example/Dockerfile --label org.argos.component=ARG-001 --label org.argos.version=$(VERSION) -t argos-example:$(VERSION) .

manifest: build
	uv run python tools/release.py build --version $(VERSION)
