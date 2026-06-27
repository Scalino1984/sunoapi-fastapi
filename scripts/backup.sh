#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p storage/backups
ZIP="storage/backups/suno_fastapi_app_backup_${TS}.zip"
zip -r "$ZIP" suno_fastapi_app.db storage/audio .env README.md >/dev/null 2>&1 || true
echo "$ZIP"
