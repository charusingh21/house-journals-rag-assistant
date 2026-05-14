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
if [ -d .venv ] && ! .venv/bin/python -c "import encodings" >/dev/null 2>&1; then
  echo "Existing virtual environment is not usable; recreating it."
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  if python3 -m venv .venv; then
    echo "Created local virtual environment."
  else
    echo "python3 -m venv is unavailable on this image; using pip3 --user fallback."
    rm -rf .venv
  fi
fi

if [ -d .venv ] && [ -x .venv/bin/python ]; then
  source .venv/bin/activate
  PYTHON_CMD="python"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  pip3 install --user -r requirements.txt
fi

mkdir -p data uploads

PDF_DIR="${HOUSE_JOURNALS_SAMPLE_DIR:-$APP_DIR/HouseJournalSample}"
INDEX_DB="${HOUSE_JOURNALS_INDEX_DB:-$APP_DIR/data/house_journals_index.sqlite}"
START_DATE="${HOUSE_JOURNALS_START_DATE:-20250101}"
END_DATE="${HOUSE_JOURNALS_END_DATE:-20261231}"
LATEST_COUNT="${HOUSE_JOURNALS_LATEST_COUNT:-0}"
CORPUS_URL="${HOUSE_JOURNALS_CORPUS_URL:-}"

if [ -n "$CORPUS_URL" ] && [ ! -d "$PDF_DIR" ]; then
  echo "Downloading House Journal corpus from HOUSE_JOURNALS_CORPUS_URL"
  mkdir -p "$(dirname "$PDF_DIR")"
  ARCHIVE_PATH="/tmp/house-journals-corpus.zip"
  if command -v curl >/dev/null 2>&1; then
    curl -L "$CORPUS_URL" -o "$ARCHIVE_PATH"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$ARCHIVE_PATH" "$CORPUS_URL"
  else
    "$PYTHON_CMD" - <<PY
import urllib.request
urllib.request.urlretrieve("$CORPUS_URL", "$ARCHIVE_PATH")
PY
  fi
  "$PYTHON_CMD" -m zipfile -e "$ARCHIVE_PATH" "$(dirname "$PDF_DIR")"
fi

if [ ! -d "$PDF_DIR" ]; then
  FOUND_PDF="$(find "$(dirname "$PDF_DIR")" -maxdepth 1 -name '*.pdf' -print -quit 2>/dev/null || true)"
  if [ -n "$FOUND_PDF" ]; then
    echo "Corpus zip extracted PDFs directly under $(dirname "$PDF_DIR"); moving them into $PDF_DIR"
    mkdir -p "$PDF_DIR"
    find "$(dirname "$PDF_DIR")" -maxdepth 1 -name '*.pdf' -exec mv {} "$PDF_DIR"/ \;
  fi
fi

if [ -d "$PDF_DIR" ] && find "$PDF_DIR" -maxdepth 1 -name '*.pdf' -print -quit | grep -q .; then
  echo "Building metadata index from $PDF_DIR"
  echo "Date range: $START_DATE to $END_DATE. Set HOUSE_JOURNALS_START_DATE/HOUSE_JOURNALS_END_DATE to change it."
  if [ "$LATEST_COUNT" != "0" ]; then
    echo "Additional PDF limit: latest $LATEST_COUNT files within date range."
  fi
  "$PYTHON_CMD" scripts/build_metadata_index.py \
    --pdf-dir "$PDF_DIR" \
    --db "$INDEX_DB" \
    --from-date "$START_DATE" \
    --to-date "$END_DATE" \
    --latest "$LATEST_COUNT"
else
  echo "No PDF sample folder found at $PDF_DIR"
  echo "Skipping metadata index build. Upload/ingest PDFs before using exact bill lookup."
fi

echo
echo "Setup complete."
echo "Next:"
echo "  1. Start or verify the NVIDIA RAG Blueprint backend."
echo "  2. Export RAG_API_URL, INGESTOR_API_URL, RAG_COLLECTION, and NVIDIA_API_KEY as needed."
echo "  3. Run ./scripts/run.sh"
