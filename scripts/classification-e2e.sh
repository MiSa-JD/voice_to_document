#!/bin/sh
set -eu

e2e_parent=${TMPDIR:-/tmp}
e2e_data_root=$(mktemp -d "$e2e_parent/voice-to-document-classification-e2e.XXXXXX")
document_host_dir="$e2e_data_root/document output"
export COMPOSE_PROJECT_NAME="voice-to-document-classification-e2e-$$"

cleanup() {
  DATA_ROOT="$e2e_data_root" docker compose down --remove-orphans >/dev/null 2>&1 || true
  case "$e2e_data_root" in
    "$e2e_parent"/voice-to-document-classification-e2e.*) rm -rf -- "$e2e_data_root" ;;
  esac
}
trap cleanup EXIT HUP INT TERM

mkdir -p \
  "$e2e_data_root/inbox" \
  "$e2e_data_root/transcripts" \
  "$e2e_data_root/speakers" \
  "$document_host_dir" \
  "$e2e_data_root/app"

export DATA_ROOT="$e2e_data_root"
export E2E_DATA_ROOT="$e2e_data_root"
export RECORDING_INPUT_HOST_DIR="$e2e_data_root/inbox"
export TRANSCRIPT_HOST_DIR="$e2e_data_root/transcripts"
export DOCUMENT_HOST_DIR="$document_host_dir"
export RECORDING_INPUT_DIR=/data/inbox
export TRANSCRIPT_ROOT=/data/transcripts
export SPEAKER_ROOT=/data/speakers
export DOCUMENT_ROOT=/data/documents
export APP_DATA_DIR=/data/app
export SCAN_INTERVAL_SECONDS=1
export FILE_STABLE_SECONDS=1
export SPEECH_MODE=fake
export DOCUMENT_MODE=real
export LLM_PROVIDER=openai_compatible
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-5.4-nano-2026-03-17
export APP_RUN_UID
APP_RUN_UID=$(id -u)
export APP_RUN_GID
APP_RUN_GID=$(id -g)
export APP_BIND_HOST=127.0.0.1
export APP_PORT
APP_PORT=$(python3 -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()')
export E2E_BASE_URL="http://127.0.0.1:$APP_PORT"

docker compose config --quiet
docker compose up --build --wait
npm --prefix frontend run test:e2e -- --grep 'real OpenAI classification'
