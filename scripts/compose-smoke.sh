#!/bin/sh
set -eu

smoke_parent=${TMPDIR:-/tmp}
smoke_data_root=$(mktemp -d "$smoke_parent/voice-to-document-smoke.XXXXXX")
document_host_dir="$smoke_data_root/document output"
export COMPOSE_PROJECT_NAME="voice-to-document-smoke-$$"

cleanup() {
  DATA_ROOT="$smoke_data_root" docker compose down --remove-orphans >/dev/null 2>&1 || true
  case "$smoke_data_root" in
    "$smoke_parent"/voice-to-document-smoke.*) rm -rf -- "$smoke_data_root" ;;
  esac
}
trap cleanup EXIT HUP INT TERM

mkdir -p \
  "$smoke_data_root/inbox" \
  "$smoke_data_root/transcripts" \
  "$smoke_data_root/speakers" \
  "$document_host_dir" \
  "$smoke_data_root/app"

export DATA_ROOT="$smoke_data_root"
export E2E_DATA_ROOT="$smoke_data_root"
export RECORDING_INPUT_HOST_DIR="$smoke_data_root/inbox"
export TRANSCRIPT_HOST_DIR="$smoke_data_root/transcripts"
export DOCUMENT_HOST_DIR="$document_host_dir"
export RECORDING_INPUT_DIR=/data/inbox
export TRANSCRIPT_ROOT=/data/transcripts
export SPEAKER_ROOT=/data/speakers
export SUMMARY_ROOT=/data/documents
export DOCUMENT_ROOT=/data/documents
export APP_DATA_DIR=/data/app
export SCAN_INTERVAL_SECONDS=1
export FILE_STABLE_SECONDS=1
export SPEECH_MODE=fake
export DOCUMENT_MODE=fake
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
host_attempt=0
until curl --fail --silent --show-error "$E2E_BASE_URL/health/live" >/dev/null; do
  host_attempt=$((host_attempt + 1))
  if [ "$host_attempt" -ge 30 ]; then
    echo "host web endpoint did not become ready" >&2
    exit 1
  fi
  sleep 1
done
make test-e2e
markdown_count=$(find "$document_host_dir" -mindepth 1 -maxdepth 1 -type f -name '*.md' | wc -l)
test "$markdown_count" -eq 1
summary_markdown_count=$(find "$document_host_dir" -mindepth 2 -type f -name '*.md' | wc -l)
summary_json_count=$(find "$document_host_dir" -mindepth 2 -type f -name '*.json' | wc -l)
test "$summary_markdown_count" -eq 1
test "$summary_json_count" -eq 1
markdown_path=$(find "$document_host_dir" -mindepth 1 -maxdepth 1 -type f -name '*.md' -print -quit)
markdown_digest=$(sha256sum "$markdown_path" | awk '{print $1}')
docker compose restart worker
npm --prefix frontend run test:e2e -- --grep 'restart preservation'
test "$(sha256sum "$markdown_path" | awk '{print $1}')" = "$markdown_digest"
