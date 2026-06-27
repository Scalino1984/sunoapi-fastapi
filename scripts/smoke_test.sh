#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
curl -fsS "$BASE_URL/health/live" >/dev/null
curl -fsS "$BASE_URL/health/ready" >/dev/null
curl -fsS "$BASE_URL/api/system/diagnostics" >/dev/null
echo "Smoke-Test OK: $BASE_URL"
