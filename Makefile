UV ?= uv
NPM := npm --prefix frontend
UV_PROJECT_ENVIRONMENT := $(CURDIR)/.venv
export UV_PROJECT_ENVIRONMENT

.PHONY: install runtime-dirs check-format lint typecheck api-schema api-schema-check test-unit test-frontend test-integration test-stt-markdown-e2e test-e2e test compose-smoke classification-eval classification-e2e model-smoke transcription-smoke alignment-smoke diarization-smoke model-eval

install:
	$(UV) sync --frozen
	$(NPM) ci

runtime-dirs:
	mkdir -p runtime/inbox runtime/transcripts runtime/speakers runtime/documents runtime/app runtime/model-cache runtime/model-eval runtime/nltk-cache
	chmod 700 runtime/nltk-cache

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

test-stt-markdown-e2e:
	$(UV) run pytest backend/tests/integration/test_stt_markdown_e2e.py

test-e2e:
	$(NPM) run test:e2e

test: test-unit test-frontend test-integration

compose-smoke:
	./scripts/compose-smoke.sh

classification-eval: runtime-dirs
	@set -eu; \
	eval_project="voice-to-document-classification-eval-$$$$"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$eval_project" docker compose down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$eval_project" docker compose --profile classification-eval run --build --rm classification-eval

classification-e2e:
	./scripts/classification-e2e.sh

model-smoke: runtime-dirs
	@set -eu; \
	model_project="voice-to-document-model-smoke-$$$$"; \
	model_uid="$$(id -u)"; \
	model_gid="$$(id -g)"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$model_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
			docker compose -f compose.yaml -f compose.gpu.yaml down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$model_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
		docker compose -f compose.yaml -f compose.gpu.yaml --profile model run --build --rm model-smoke

transcription-smoke: runtime-dirs
	@set -eu; \
	transcription_project="voice-to-document-transcription-smoke-$$$$"; \
	model_uid="$$(id -u)"; \
	model_gid="$$(id -g)"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$transcription_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
			docker compose -f compose.yaml -f compose.gpu.yaml down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$transcription_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
		docker compose -f compose.yaml -f compose.gpu.yaml --profile transcription run --build --rm transcription-smoke

alignment-smoke: runtime-dirs
	@set -eu; \
	alignment_project="voice-to-document-alignment-smoke-$$$$"; \
	model_uid="$$(id -u)"; \
	model_gid="$$(id -g)"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$alignment_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
			docker compose -f compose.yaml -f compose.gpu.yaml down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$alignment_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
		docker compose -f compose.yaml -f compose.gpu.yaml --profile alignment run --build --rm alignment-smoke

diarization-smoke: runtime-dirs
	@set -eu; \
	diarization_project="voice-to-document-diarization-smoke-$$$$"; \
	model_uid="$$(id -u)"; \
	model_gid="$$(id -g)"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$diarization_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
			docker compose -f compose.yaml -f compose.gpu.yaml down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$diarization_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
		docker compose -f compose.yaml -f compose.gpu.yaml --profile diarization run --build --rm diarization-smoke

model-eval: runtime-dirs
	@set -eu; \
	eval_project="voice-to-document-model-eval-$$$$"; \
	model_uid="$$(id -u)"; \
	model_gid="$$(id -g)"; \
	cleanup() { \
		COMPOSE_PROJECT_NAME="$$eval_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
			docker compose -f compose.yaml -f compose.gpu.yaml down --remove-orphans >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT HUP INT TERM; \
	COMPOSE_PROJECT_NAME="$$eval_project" MODEL_RUN_UID="$$model_uid" MODEL_RUN_GID="$$model_gid" \
		docker compose -f compose.yaml -f compose.gpu.yaml --profile model-eval run --build --rm model-eval
