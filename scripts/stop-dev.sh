#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT_DIR/.runtime/pids"
FASTAPI_PID_FILE="$PID_DIR/fastapi.pid"
REACT_PID_FILE="$PID_DIR/react.pid"
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
REACT_PORT="${REACT_PORT:-5173}"

kill_pid_tree() {
  local pid="$1"

  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0

  local children=""
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  if [[ -n "$children" ]]; then
    local child
    for child in $children; do
      kill_pid_tree "$child"
    done
  fi

  kill "$pid" 2>/dev/null || true
}

force_kill_pid_tree() {
  local pid="$1"

  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0

  local children=""
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  if [[ -n "$children" ]]; then
    local child
    for child in $children; do
      force_kill_pid_tree "$child"
    done
  fi

  kill -9 "$pid" 2>/dev/null || true
}

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

kill_port_processes() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(port_pids "$port")"

  if [[ -z "$pids" ]]; then
    return 0
  fi

  echo "Stoppe verbleibende $name-Prozesse auf Port $port: $pids"
  local pid
  for pid in $pids; do
    kill_pid_tree "$pid"
  done

  for _ in {1..20}; do
    if [[ -z "$(port_pids "$port")" ]]; then
      return 0
    fi
    sleep 0.2
  done

  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    echo "$name auf Port $port reagiert nicht, erzwinge Stop: $pids"
    for pid in $pids; do
      force_kill_pid_tree "$pid"
    done
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name: keine PID-Datei vorhanden. Prüfe Port $port ..."
    kill_port_processes "$name" "$port"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"

  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "$name: leere PID-Datei entfernt. Prüfe Port $port ..."
    kill_port_processes "$name" "$port"
    return 0
  fi

  if kill -0 "$pid" 2>/dev/null; then
    echo "Stoppe $name PID $pid ..."
    kill_pid_tree "$pid"

    for _ in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "$name PID $pid reagiert nicht, erzwinge Stop ..."
      force_kill_pid_tree "$pid"
    fi
  else
    echo "$name PID $pid läuft nicht mehr."
  fi

  kill_port_processes "$name" "$port"
  rm -f "$pid_file"

  if [[ -n "$(port_pids "$port")" ]]; then
    echo "WARNUNG: $name-Port $port ist weiterhin belegt." >&2
    return 1
  fi

  echo "$name gestoppt."
}

stop_process "React/Vite" "$REACT_PID_FILE" "$REACT_PORT"
stop_process "FastAPI" "$FASTAPI_PID_FILE" "$FASTAPI_PORT"
