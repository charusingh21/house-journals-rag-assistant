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

export RAG_COLLECTION="${RAG_COLLECTION:-house_journals_full_demo}"
export HOUSE_JOURNALS_SAMPLE_DIR="${HOUSE_JOURNALS_SAMPLE_DIR:-$APP_DIR/HouseJournalSample}"
export HOUSE_JOURNALS_INDEX_DB="${HOUSE_JOURNALS_INDEX_DB:-$APP_DIR/data/house_journals_index.sqlite}"

./scripts/setup.sh
./scripts/start_rag_blueprint_gpu.sh

if [ -d "$HOUSE_JOURNALS_SAMPLE_DIR" ] && [ -f "$HOUSE_JOURNALS_INDEX_DB" ]; then
  python3 scripts/ingest_house_journals.py \
    --pdf-dir "$HOUSE_JOURNALS_SAMPLE_DIR" \
    --db "$HOUSE_JOURNALS_INDEX_DB" \
    --collection "$RAG_COLLECTION" \
    --latest "${HOUSE_JOURNALS_INGEST_LATEST:-40}"
fi

./scripts/run.sh
