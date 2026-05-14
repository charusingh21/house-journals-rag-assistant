#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_CMD="python3"
if [ -d .venv ] && [ -x .venv/bin/python ]; then
  source .venv/bin/activate
  PYTHON_CMD="python"
fi

export RAG_COLLECTION="${RAG_COLLECTION:-house_journals_full_demo}"
export RAG_API_URL="${RAG_API_URL:-http://127.0.0.1:8081/v1/generate}"
export INGESTOR_API_URL="${INGESTOR_API_URL:-http://127.0.0.1:8082/v1/documents}"
export HOUSE_JOURNALS_SAMPLE_DIR="${HOUSE_JOURNALS_SAMPLE_DIR:-$APP_DIR/HouseJournalSample}"
export HOUSE_JOURNALS_INDEX_DB="${HOUSE_JOURNALS_INDEX_DB:-$APP_DIR/data/house_journals_index.sqlite}"
export HOUSE_JOURNALS_START_DATE="${HOUSE_JOURNALS_START_DATE:-20250101}"
export HOUSE_JOURNALS_END_DATE="${HOUSE_JOURNALS_END_DATE:-20261231}"
export HOUSE_JOURNALS_LATEST_COUNT="${HOUSE_JOURNALS_LATEST_COUNT:-0}"
export RAG_MODEL="${RAG_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"
export RAG_MAX_TOKENS="${RAG_MAX_TOKENS:-700}"
export RAG_DEFAULT_PROFILE="${RAG_DEFAULT_PROFILE:-balanced}"
if [ -z "${RAG_MODEL_PROFILES:-}" ]; then
  if [ "${RAG_BACKEND_MODE:-nvidia_hosted}" = "docker_self_hosted" ]; then
    export RAG_MODEL_PROFILES="balanced=$RAG_MODEL|$RAG_MAX_TOKENS|Balanced"
  else
    export RAG_MODEL_PROFILES="fast=nvidia/nemotron-3-nano-30b-a3b|450|Fast demo;llama31=meta/llama-3.1-8b-instruct|700|Llama 3.1 8B;balanced=nvidia/llama-3.3-nemotron-super-49b-v1.5|700|Nemotron Super 49B;deep=nvidia/llama-3.3-nemotron-super-49b-v1.5|1100|Deep research"
  fi
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5056}"

echo "Starting House Journals Research Assistant"
echo "UI: http://$HOST:$PORT"
echo "RAG API: $RAG_API_URL"
echo "Ingestor API: $INGESTOR_API_URL"
echo "Collection: $RAG_COLLECTION"
echo "Default profile: $RAG_DEFAULT_PROFILE"

exec "$PYTHON_CMD" app.py --host "$HOST" --port "$PORT"
