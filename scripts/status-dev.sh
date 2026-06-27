#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT_DIR/.runtime/pids"
FASTAPI_PID_FILE="$PID_DIR/fastapi.pid"
REACT_PID_FILE="$PID_DIR/react.pid"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
REACT_PORT="${REACT_PORT:-5173}"

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "$port"/tcp 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true
  else
    true
  fi
}

status_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local pid=""
  local pids=""

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi

  pids="$(port_pids "$port")"

  if [[ -n "$pid" && $(kill -0 "$pid" 2>/dev/null; echo $?) -eq 0 ]]; then
    if [[ -n "$pids" ]]; then
      echo "$name: läuft | PID-Datei $pid | Port $port belegt durch $pids"
    else
      echo "$name: Prozess läuft, aber Port $port ist nicht belegt | PID $pid"
    fi
    return 0
  fi

  if [[ -n "$pids" ]]; then
    echo "$name: Port $port ist belegt durch $pids | PID-Datei fehlt/veraltet"
    return 0
  fi

  echo "$name: gestoppt | Port $port frei"
}

status_process "FastAPI" "$FASTAPI_PID_FILE" "$FASTAPI_PORT"
status_process "React/Vite" "$REACT_PID_FILE" "$REACT_PORT"
