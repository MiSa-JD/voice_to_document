#!/bin/sh
set -eu

smoke_parent=${TMPDIR:-/tmp}
smoke_data_root=$(mktemp -d "$smoke_parent/voice-to-document-smoke.XXXXXX")

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
  "$smoke_data_root/documents" \
  "$smoke_data_root/app"

export DATA_ROOT="$smoke_data_root"
export E2E_DATA_ROOT="$smoke_data_root"
export SCAN_INTERVAL_SECONDS=1
export FILE_STABLE_SECONDS=1

docker compose config --quiet
docker compose up --build --wait
host_attempt=0
until curl --fail --silent --show-error http://127.0.0.1:8000/health/live >/dev/null; do
  host_attempt=$((host_attempt + 1))
  if [ "$host_attempt" -ge 30 ]; then
    echo "host web endpoint did not become ready" >&2
    exit 1
  fi
  sleep 1
done
npm --prefix frontend run test:e2e -- --grep 'pipeline flow|브라우저에서'
docker compose restart worker
npm --prefix frontend run test:e2e -- --grep 'restart preservation'
