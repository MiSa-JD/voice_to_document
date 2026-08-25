UV ?= uv
NPM := npm --prefix frontend
UV_PROJECT_ENVIRONMENT := $(CURDIR)/.venv
export UV_PROJECT_ENVIRONMENT

.PHONY: install runtime-dirs check-format lint typecheck api-schema api-schema-check test-unit test-frontend test-integration test-e2e test compose-smoke model-eval

install:
	$(UV) sync --frozen
	$(NPM) ci

runtime-dirs:
	mkdir -p runtime/inbox runtime/transcripts runtime/speakers runtime/documents runtime/app

check-format:
	$(UV) run ruff format --check backend
	$(NPM) run format:check

lint:
	$(UV) run ruff check backend
	$(NPM) run lint

typecheck:
	$(UV) run mypy
	$(NPM) run typecheck

api-schema:
	$(UV) run python -m app.openapi --write
	$(NPM) run api:generate

api-schema-check:
	$(UV) run python -m app.openapi --check
	$(NPM) run api:types:check

test-unit:
	$(UV) run pytest backend/tests/unit

test-frontend:
	$(NPM) test

test-integration:
	$(UV) run pytest backend/tests/integration

test-e2e:
	$(NPM) run test:e2e

test: test-unit test-frontend test-integration

compose-smoke:
	./scripts/compose-smoke.sh

model-eval:
	@echo "R4에서 Linux NVIDIA GPU와 실제 모델 환경을 준비한 뒤 사용할 수 있습니다." >&2
	@exit 2
