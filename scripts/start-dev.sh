#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"
FASTAPI_PID_FILE="$PID_DIR/fastapi.pid"
REACT_PID_FILE="$PID_DIR/react.pid"
FASTAPI_LOG="$LOG_DIR/fastapi.log"
REACT_LOG="$LOG_DIR/react.log"

FASTAPI_HOST="${FASTAPI_HOST:-0.0.0.0}"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
REACT_HOST="${REACT_HOST:-0.0.0.0}"
REACT_PORT="${REACT_PORT:-5173}"
AUTO_NPM_INSTALL="${AUTO_NPM_INSTALL:-true}"

python3 -m compileall -q app scripts

mkdir -p "$PID_DIR" "$LOG_DIR"
cd "$ROOT_DIR"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

port_pid() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "$port"/tcp 2>/dev/null | awk '{print $1}' | head -n 1 || true
  else
    true
  fi
}

wait_for_port_pid() {
  local port="$1"
  local fallback_pid="$2"
  local found_pid=""

  for _ in {1..30}; do
    found_pid="$(port_pid "$port")"
    if [[ -n "$found_pid" ]]; then
      echo "$found_pid"
      return 0
    fi
    if ! kill -0 "$fallback_pid" 2>/dev/null; then
      echo "$fallback_pid"
      return 0
    fi
    sleep 0.2
  done

  echo "$fallback_pid"
}

resolve_uvicorn() {
  if [[ -x "$ROOT_DIR/venv/bin/uvicorn" ]]; then
    echo "$ROOT_DIR/venv/bin/uvicorn"
  elif [[ -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
    echo "$ROOT_DIR/.venv/bin/uvicorn"
  else
    command -v uvicorn
  fi
}

start_fastapi() {
  if is_running "$FASTAPI_PID_FILE"; then
    echo "FastAPI läuft bereits mit PID $(cat "$FASTAPI_PID_FILE")"
    return 0
  fi

  local existing_pid
  existing_pid="$(port_pid "$FASTAPI_PORT")"
  if [[ -n "$existing_pid" ]]; then
    echo "FastAPI-Port $FASTAPI_PORT ist bereits belegt durch PID $existing_pid."
    echo "$existing_pid" > "$FASTAPI_PID_FILE"
    return 0
  fi

  local uvicorn_bin
  uvicorn_bin="$(resolve_uvicorn)"

  echo "Starte FastAPI auf http://$FASTAPI_HOST:$FASTAPI_PORT ..."
  nohup "$uvicorn_bin" app.main:app \
    --host "$FASTAPI_HOST" \
    --port "$FASTAPI_PORT" \
    --reload \
    > "$FASTAPI_LOG" 2>&1 &

  local starter_pid=$!
  local listener_pid
  listener_pid="$(wait_for_port_pid "$FASTAPI_PORT" "$starter_pid")"
  echo "$listener_pid" > "$FASTAPI_PID_FILE"
  sleep 1

  if ! is_running "$FASTAPI_PID_FILE"; then
    echo "FastAPI konnte nicht gestartet werden. Log:" >&2
    tail -80 "$FASTAPI_LOG" >&2 || true
    exit 1
  fi

  echo "FastAPI gestartet: PID $(cat "$FASTAPI_PID_FILE")"
}

start_react() {
  if [[ ! -d "$ROOT_DIR/frontend-react" ]]; then
    echo "frontend-react/ nicht gefunden, React wird übersprungen."
    return 0
  fi

  if is_running "$REACT_PID_FILE"; then
    echo "React läuft bereits mit PID $(cat "$REACT_PID_FILE")"
    return 0
  fi

  local existing_pid
  existing_pid="$(port_pid "$REACT_PORT")"
  if [[ -n "$existing_pid" ]]; then
    echo "React-Port $REACT_PORT ist bereits belegt durch PID $existing_pid."
    echo "$existing_pid" > "$REACT_PID_FILE"
    return 0
  fi

  if [[ "$AUTO_NPM_INSTALL" == "true" && ! -d "$ROOT_DIR/frontend-react/node_modules" ]]; then
    echo "React-Abhängigkeiten fehlen. Führe npm install aus ..."
    npm --prefix "$ROOT_DIR/frontend-react" install
  fi

  echo "Starte React/Vite auf http://$REACT_HOST:$REACT_PORT ..."

  # Wichtig: Vite muss mit frontend-react/ als Arbeitsverzeichnis starten.
  # Wird die Vite-Binary aus dem Projektwurzelverzeichnis gestartet, lauscht
  # zwar ein Node-Prozess auf 5173, aber / liefert HTTP 404, weil Vite dort
  # keine index.html findet.
  (
    cd "$ROOT_DIR/frontend-react"
    if [[ -x "node_modules/.bin/vite" ]]; then
      nohup "node_modules/.bin/vite" \
        --host "$REACT_HOST" \
        --port "$REACT_PORT" \
        > "$REACT_LOG" 2>&1 &
    else
      nohup npm run dev -- \
        --host "$REACT_HOST" \
        --port "$REACT_PORT" \
        > "$REACT_LOG" 2>&1 &
    fi
    echo $!
  ) > "$PID_DIR/react-starter.pid"

  local starter_pid
  starter_pid="$(cat "$PID_DIR/react-starter.pid" 2>/dev/null || true)"
  rm -f "$PID_DIR/react-starter.pid"
  if [[ -z "$starter_pid" ]]; then
    echo "React-Starter-PID konnte nicht ermittelt werden." >&2
    tail -80 "$REACT_LOG" >&2 || true
    exit 1
  fi

  local listener_pid
  listener_pid="$(wait_for_port_pid "$REACT_PORT" "$starter_pid")"
  echo "$listener_pid" > "$REACT_PID_FILE"
  sleep 1

  if ! is_running "$REACT_PID_FILE"; then
    echo "React konnte nicht gestartet werden. Log:" >&2
    tail -80 "$REACT_LOG" >&2 || true
    exit 1
  fi

  echo "React gestartet: PID $(cat "$REACT_PID_FILE")"
}

start_fastapi
start_react

echo ""
echo "Dienste laufen im Hintergrund."
echo "FastAPI: http://127.0.0.1:$FASTAPI_PORT"
echo "React:   http://127.0.0.1:$REACT_PORT"
echo "Logs:    npm run logs"
echo "Stop:    npm run stop"
