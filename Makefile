# ARGOS · monorepo orchestration (ARG-001).
# Recipes are plain commands that behave the same under sh (CI) and cmd (Windows):
# SHELL is not set because on Windows "bash" may resolve to the WSL launcher.
COMPOSE := docker compose -f deploy/dev/compose.yaml

.PHONY: help dev dev-down lint typecheck secrets test check cover

help:
	@echo "make dev        start the development environment (docker)"
	@echo "make dev-down   stop it"
	@echo "make test       unit tests"
	@echo "make check      lint + typecheck + secrets + all tests (needs make dev)"
	@echo "make cover      all tests with coverage threshold (needs make dev)"

dev:
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root vault sh -s < deploy/dev/vault/setup.sh
	uv run --env-file .env.example python tools/migrate.py

dev-down:
	$(COMPOSE) down

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy libs services

secrets:
	gitleaks detect --no-banner --redact

test:
	uv run pytest -m "not integration"

check: lint typecheck secrets
	uv run pytest

cover:
	uv run pytest --cov=argos_common --cov=argos_events --cov=argos_auth --cov-report=term-missing --cov-fail-under=80
