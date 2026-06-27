#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/5] Python-Compile"
python3 -m compileall -q app scripts

echo "[2/5] Audit"
python3 scripts/audit_unified_audio_state.py "$@"

echo "[3/5] Migration Dry-Run"
python3 scripts/migrate_unified_audio_library.py --dry-run --backup "$@"

echo "[4/5] Validierung"
python3 scripts/validate_unified_audio_workflow.py "$@"

echo "[5/5] Report"
python3 scripts/export_unified_audio_report.py "$@"

echo "Fertig."
