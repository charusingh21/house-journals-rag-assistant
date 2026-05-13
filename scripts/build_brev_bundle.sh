#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

ARCHIVE_NAME="${1:-house-journals-blueprint-assistant.tar.gz}"

tar \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.env' \
  -czf "$ARCHIVE_NAME" \
  app.py static scripts requirements.txt .env.example README_BREV.md

echo "Created $ARCHIVE_NAME"
