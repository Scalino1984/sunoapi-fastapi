#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/storage/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ZIP_NAME="${ZIP_NAME:-sunoapi-fastapi-ai-test-${STAMP}.zip}"
ZIP_PATH="${OUT_DIR}/${ZIP_NAME}"
SNAPSHOT_DIR="$(mktemp -d)"
SNAPSHOT_RELATIVE="documentation/storage_snapshot.txt"
SNAPSHOT_FILE="${SNAPSHOT_DIR}/${SNAPSHOT_RELATIVE}"

mkdir -p "$OUT_DIR" "$(dirname "$SNAPSHOT_FILE")"
rm -f "$ZIP_PATH"

cd "$ROOT_DIR"

create_storage_snapshot() {
  {
    echo "# Storage Snapshot"
    echo
    echo "Generated: $(date -Iseconds)"
    echo "Source root: storage/"
    echo
    echo "## Inventory"
    if [[ -d storage ]]; then
      find storage -type f | sort | while IFS= read -r file; do
        size="$(wc -c < "$file" | tr -d ' ')"
        sha="$(sha256sum "$file" | awk '{print $1}')"
        printf '%s | %s bytes | %s\n' "$file" "$size" "$sha"
      done
    else
      echo "storage/ not found"
    fi
    echo
    echo "## Text Contents"
    if [[ -d storage ]]; then
      find storage -type f | sort | while IFS= read -r file; do
        case "$file" in
          *.txt|*.md|*.json|*.csv|*.srt|*.log|*.py|*.js|*.jsx|*.ts|*.tsx|*.css|*.html|*.yaml|*.yml|*.ini|*.conf)
            echo
            echo "### $file"
            echo '```text'
            cat "$file"
            echo '```'
            ;;
        esac
      done
    fi
    echo
    echo "## Binary Or Media Files"
    if [[ -d storage ]]; then
      find storage -type f | sort | while IFS= read -r file; do
        case "$file" in
          *.txt|*.md|*.json|*.csv|*.srt|*.log|*.py|*.js|*.jsx|*.ts|*.tsx|*.css|*.html|*.yaml|*.yml|*.ini|*.conf)
            ;;
          *)
            size="$(wc -c < "$file" | tr -d ' ')"
            sha="$(sha256sum "$file" | awk '{print $1}')"
            echo
            echo "### $file"
            echo "binary_or_media=true size=${size} sha256=${sha}"
            ;;
        esac
      done
    fi
  } > "$SNAPSHOT_FILE"
}

create_storage_snapshot

INCLUDE_ITEMS=(
  "app"
  "frontend-react/src"
  "frontend-react/public"
  "frontend-react/index.html"
  "frontend-react/package.json"
  "frontend-react/package-lock.json"
  "frontend-react/vite.config.js"
  "tests"
  "migrations"
  "alembic.ini"
  "requirements.txt"
  "requirements-whisperx.txt"
  "requirements-stems.txt"
  "pytest.ini"
  "docker-compose.yml"
  "Dockerfile"
  "scripts"
  "documentation"
  "README.md"
  "GIT-README.md"
  "PROJECT_BASELINE_SUNOAPI_2026-06-20.md"
  "RELEASE_FINALIZED.md"
  "CODEBASE_ANALYSE.md"
  "DATABASE_SCHEMA_OVERVIEW_AI_AGENTS.md"
  "KI_FUNKTIONEN_SYSTEM_PROMPTS_PROVIDER.md"
)

EXCLUDES=(
  "*/node_modules/*"
  "*/venv/*"
  "*/.venv/*"
  "*/__pycache__/*"
  "*/.pytest_cache/*"
  "*/.mypy_cache/*"
  "*/.ruff_cache/*"
  "*/.git/*"
  "*/dist/*"
  "*/build/*"
  "*/.codex/*"
  "*/logs/*"
  "*/.runtime/*"
  "storage/*"
  "*.sqlite3-wal"
  "*.sqlite3-shm"
  "*.db-wal"
  "*.db-shm"
  "*.mp3"
  "*.wav"
  "*.mp4"
  "*.webm"
  "*.m4a"
  "*.flac"
  "*.ogg"
  "*.gif"
  "*.zip"
  "*.tar"
  "*.tar.gz"
  "*.bak"
  "*.bck"
  ".env"
  ".env.*"
  "*/.env"
  "*/.env.*"
)

zip -r "$ZIP_PATH" "${INCLUDE_ITEMS[@]}" -x "${EXCLUDES[@]}" >/dev/null

cd "$SNAPSHOT_DIR"
zip -g -r "$ZIP_PATH" "$SNAPSHOT_RELATIVE" >/dev/null

echo "$ZIP_PATH"
