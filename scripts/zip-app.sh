#!/bin/bash


# PFAD="${1:-$PWD}"

PFAD="$HOME/Projekte"
ZIPNAME="sunoapi-fastapi-srv.zip"

echo "$PFAD"

zip -r "$PFAD/$ZIPNAME" \ 
  app \
  frontend-react/src \
  frontend-react/index.html \
  frontend-react/package.json \
  frontend-react/package-lock.json \
  frontend-react/vite.config.js \
  frontend-react/public \
  scripts \
  requirements.txt \
  pyproject.toml \
  alembic.ini \
  .env.example \
  README.md \
  -x \
  "*/node_modules/*" \
  "*/venv/*" \
  "*/.venv/*" \
  "*/__pycache__/*" \
  "*/.pytest_cache/*" \
  "*/.mypy_cache/*" \
  "*/.ruff_cache/*" \
  "*/.git/*" \
  "*/dist/*" \
  "*/build/*" \
  "*/storage/*" \
  "*/covers/*" \
  "*/transcripts/*" \
  "*/uploads/*" \
  "*/logs/*" \
  "*/.runtime/*" \
  "*/test_suno/*" \
  "*.sqlite3" \
  "*.db" \
  "*.db-wal" \
  "*.db-shm" \
  "*.mp3" \
  "*.wav" \
  "*.mp4" \
  "*.webm" \
  "*.m4a" \
  "*.flac" \
  "*.ogg" \
  "*.gif" \
  "*.zip" \
  "*.tar" \
  "*.tar.gz" \
  "*.bak" \
  "*.bck" \
  ".env" \
  ".env.*" \
  "*/.env" \
  "*/.env.*"

echo -e "\ndone...\n"
