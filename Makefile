# ARGOS · monorepo orchestration (ARG-001).
# Recipes are plain commands that behave the same under sh (CI) and cmd (Windows):
# SHELL is not set because on Windows "bash" may resolve to the WSL launcher.
COMPOSE := docker compose -f deploy/dev/compose.yaml --profile sources
COMPOSE_HEAVY := docker compose -f deploy/dev/compose.yaml --profile sources --profile heavy
VERSION := $(strip $(file < VERSION))

.PHONY: help dev dev-heavy dev-down lint typecheck secrets test check check-heavy cover build manifest docs-check ontology-gates policy-test ontology-overlap challenge-lint challenge-catalog api-contract api-contract-write console-install console-lint console-test console-types console-build ai-eval ai-eval-release demo demo-reset

help:
	@echo "make dev        start the development environment and simulated sources (docker)"
	@echo "make dev-heavy  also start SQL Server and Oracle (several GB of RAM)"
	@echo "make dev-down   stop it"
	@echo "make test       unit tests"
	@echo "make check      lint + typecheck + secrets + all tests (needs make dev)"
	@echo "make cover      all tests with coverage threshold (needs make dev)"
	@echo "make check-heavy tests that need make dev-heavy"
	@echo "make manifest   build images and write dist/release-manifest.json"
	@echo "make docs-check     technical documentation covers every module and closed phase"
	@echo "make ontology-gates  the five editorial gates of the ontology"
	@echo "make policy-test    Rego unit tests in the OPA container"
	@echo "make ontology-overlap  overlap matrix between norms (dist/overlap.*)"
	@echo "make challenge-lint   the challenge library against its schema and rules"
	@echo "make challenge-catalog  the generated challenge catalog is up to date"
	@echo "make api-contract   the versioned v1 contract matches the application"
	@echo "make console-install  install the console dependencies from package-lock.json (npm ci)"
	@echo "make console-lint   strict TypeScript and the colour rules of the console"
	@echo "make console-test   the console tests (Vitest)"
	@echo "make console-types  the console types match the v1 contract"
	@echo "make console-build  build the console into console/dist"
	@echo "make ai-eval       golden sets of the AI layer with the oracle (also inside make check)"
	@echo "make ai-eval-release  golden sets against the served model: release gate (needs weights)"
	@echo "make demo         MVP demonstration end to end, outputs in .scratch/demo (needs make dev)"
	@echo "make demo-reset   drop every volume and start the environment again, clean for a demonstration"

dev:
	uv run python tools/prepare_dev_sources.py
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root vault sh -s < deploy/dev/vault/setup.sh
	uv run --env-file .env.example python tools/migrate.py
	uv run --env-file .env.example python tools/register_dev_sources.py
	uv run python tools/seed_dev_clinical.py

dev-heavy: dev
	$(COMPOSE_HEAVY) up -d --wait
	$(COMPOSE_HEAVY) exec -T source-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P Dev-Only-Sa-2026 -i /init/01-erp.sql

dev-down:
	$(COMPOSE_HEAVY) down

# The demonstration environment from nothing: every volume goes (development data, WORM store,
# TSA test CA), then `make dev` builds, migrates, registers and seeds the sources again.
demo-reset:
	$(COMPOSE_HEAVY) down -v
	$(MAKE) dev

demo:
	uv run python tools/demo/run_mvp_demo.py --out .scratch/demo

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy libs services connectors

secrets:
	gitleaks detect --no-banner --redact

test:
	uv run pytest -m "not integration"

check: lint typecheck secrets docs-check api-contract console-lint console-test console-types
	uv run pytest -m "not heavy"

check-heavy:
	uv run pytest -m heavy

cover:
	uv run pytest -m "not heavy" --cov=argos_common --cov=argos_events --cov=argos_auth --cov=argos_connector --cov=argos_sql --cov=argos_files --cov=argos_rest --cov=argos_ldap --cov=argos_dicom --cov=argos_fhir --cov=argos_inventory --cov=argos_ontology --cov-report=term-missing --cov-fail-under=80

build:
	docker build -f services/example/Dockerfile --label org.argos.component=ARG-001 --label org.argos.version=$(VERSION) -t argos-example:$(VERSION) .
	docker build -f services/challenge-engine/Dockerfile --label org.argos.component=ARG-043 --label org.argos.version=$(VERSION) -t argos-challenge-engine:$(VERSION) .
	docker build -f services/ai-gateway/Dockerfile --label org.argos.component=ARG-052 --label org.argos.version=$(VERSION) -t argos-ai-gateway:$(VERSION) .

manifest: build
	uv run python tools/release.py build --version $(VERSION)

docs-check:
	uv run python tools/docs_pack.py --check

ontology-gates:
	uv run python tools/ontology_gates.py

policy-test:
	$(COMPOSE) run --rm --no-deps opa test /policies -v

ontology-overlap:
	uv run python tools/ontology_overlap.py --output dist

challenge-lint:
	uv run python tools/challenge_lint.py

challenge-catalog:
	uv run python tools/challenge_catalog.py --check

api-contract:
	uv run python tools/api_contract.py --check

api-contract-write:
	uv run python tools/api_contract.py

# The console (ADR-0013): npm with its lock file, never a CDN.
console-install:
	npm --prefix console ci --no-fund --no-audit

console-lint:
	npm --prefix console run typecheck
	npm --prefix console run lint:css

console-test:
	npm --prefix console run test

console-types:
	npm --prefix console run api:check

console-build:
	npm --prefix console run build

ai-eval:
	uv run pytest -m integration tests/integration/test_ai_goldens.py

ai-eval-release:
	uv run --env-file .env.example python tools/ai_eval/run_goldens.py
