#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.runtime/logs"
FASTAPI_LOG="$LOG_DIR/fastapi.log"
REACT_LOG="$LOG_DIR/react.log"

mkdir -p "$LOG_DIR"
touch "$FASTAPI_LOG" "$REACT_LOG"

echo "Zeige FastAPI- und React-Logs. Abbrechen mit STRG+C."
tail -f "$FASTAPI_LOG" "$REACT_LOG"
