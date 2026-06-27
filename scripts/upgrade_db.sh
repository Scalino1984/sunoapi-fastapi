#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v alembic >/dev/null 2>&1; then
  alembic upgrade head
else
  echo "Alembic ist nicht installiert. Bitte: pip install -r requirements.txt" >&2
  exit 1
fi
