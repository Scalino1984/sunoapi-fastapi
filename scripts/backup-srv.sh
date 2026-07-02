#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="songstudio"
PROJECT_DIR="/opt/songstudio"
BACKUP_DIR="/root/.backups"
TIMESTAMP="$(date +"%Y-%m-%d_%H-%M-%S")"
BACKUP_FILE="${BACKUP_DIR}/${APP_NAME}_backup_${TIMESTAMP}.zip"
LOG_FILE="${BACKUP_DIR}/${APP_NAME}_backup.log"
KEEP_BACKUPS=14
SERVICE_NAME="songstudio-vanilla"

EXCLUDES=(
  "*/node_modules/*"
  "*/.venv/*"
  "*/venv/*"
  "*/__pycache__/*"
  "*/.pytest_cache/*"
  "*/.mypy_cache/*"
  "*/.ruff_cache/*"
  "*/.cache/*"
  "*/frontend-react/node_modules/*"
  "*/frontend-react/.vite/*"
  "*/frontend-react/dist/*"
  "*/.runtime/logs/*"
  "*.pyc"
  "*.pyo"
  "*.log"
  "*.tmp"
  "*.swp"
  "*.bak"
)

log() {
  mkdir -p "$BACKUP_DIR"
  echo "[$(date +"%Y-%m-%d %H:%M:%S")] $*" | tee -a "$LOG_FILE"
}

fail() {
  log "FEHLER: $*"
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Benötigter Befehl fehlt: $1"
}

prepare_backup_dir() {
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
}

check_project_dir() {
  [[ -d "$PROJECT_DIR" ]] || fail "Projektordner existiert nicht: $PROJECT_DIR"
}

check_service_status() {
  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
      log "Service läuft: ${SERVICE_NAME}"
    else
      log "WARNUNG: Service läuft nicht: ${SERVICE_NAME}"
    fi
  else
    log "WARNUNG: Service nicht gefunden: ${SERVICE_NAME}"
  fi
}

sqlite_checkpoint() {
  local db_file="${PROJECT_DIR}/storage/app.db"

  if [[ -f "$db_file" ]]; then
    if command -v sqlite3 >/dev/null 2>&1; then
      log "SQLite WAL-Checkpoint: $db_file"
      sqlite3 "$db_file" "PRAGMA wal_checkpoint(FULL);" || log "WARNUNG: SQLite Checkpoint fehlgeschlagen"
    else
      log "WARNUNG: sqlite3 fehlt, Checkpoint wird übersprungen"
    fi
  else
    log "WARNUNG: Datenbank nicht gefunden: $db_file"
  fi
}

create_backup() {
  local exclude_args=()

  for pattern in "${EXCLUDES[@]}"; do
    exclude_args+=("-x" "$pattern")
  done

  log "Backup startet"
  log "Quelle: $PROJECT_DIR"
  log "Ziel:   $BACKUP_FILE"

  cd "$(dirname "$PROJECT_DIR")"

  zip -r "$BACKUP_FILE" "$(basename "$PROJECT_DIR")" "${exclude_args[@]}" >/dev/null

  [[ -f "$BACKUP_FILE" ]] || fail "Backup-Datei wurde nicht erstellt"

  chmod 600 "$BACKUP_FILE"

  local size
  size="$(du -h "$BACKUP_FILE" | awk '{print $1}')"

  log "Backup erstellt: $BACKUP_FILE"
  log "Größe: $size"
}

verify_backup() {
  log "Prüfe ZIP-Integrität"

  if zip -T "$BACKUP_FILE" >/dev/null; then
    log "ZIP-Integritätsprüfung erfolgreich"
  else
    fail "ZIP-Integritätsprüfung fehlgeschlagen"
  fi
}

cleanup_old_backups() {
  log "Bereinige alte Backups, behalte letzte ${KEEP_BACKUPS}"

  find "$BACKUP_DIR" -maxdepth 1 -type f -name "${APP_NAME}_backup_*.zip" \
    | sort -r \
    | tail -n +$((KEEP_BACKUPS + 1)) \
    | while read -r old_backup; do
        log "Lösche altes Backup: $old_backup"
        rm -f "$old_backup"
      done
}

main() {
  require_command zip
  require_command find
  require_command systemctl

  prepare_backup_dir
  check_project_dir
  check_service_status
  sqlite_checkpoint
  create_backup
  verify_backup
  cleanup_old_backups

  log "Backup abgeschlossen"
}

main "$@"

