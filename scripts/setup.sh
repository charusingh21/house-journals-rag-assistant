#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

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
