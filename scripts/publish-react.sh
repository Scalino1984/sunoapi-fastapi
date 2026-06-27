#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="songstudio-react"
PROJECT_DIR="/opt/songstudio"
FRONTEND_DIR="${PROJECT_DIR}/frontend-react"
BUILD_DIR="${FRONTEND_DIR}/dist"
WEB_DIR="/var/www/songstudio-react"
BACKUP_DIR="/root/.backups/react-publish"
LOG_FILE="/root/.backups/songstudio_react_publish.log"

APACHE_SERVICE="apache2"
API_SERVICE="songstudio-vanilla"
API_LOCAL_BASE="${API_LOCAL_BASE:-http://127.0.0.1:8000}"
WEB_USER="www-data"
WEB_GROUP="www-data"
KEEP_PUBLISH_BACKUPS=5

log() {
  mkdir -p "$(dirname "$LOG_FILE")"
  echo "[$(date +"%Y-%m-%d %H:%M:%S")] $*" | tee -a "$LOG_FILE"
}

fail() {
  log "FEHLER: $*"
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Benötigter Befehl fehlt: $1"
}

http_code() {
  local url="$1"
  local method="${2:-GET}"
  local code

  code="$(curl -k -s -o /dev/null -w "%{http_code}" -X "$method" "$url" 2>/dev/null || true)"
  if [[ -z "$code" ]]; then
    code="000"
  fi

  echo "$code"
}

print_expected_http_check() {
  local title="$1"
  local url="$2"
  local expected_code="$3"
  local ok_message="$4"
  local method="${5:-GET}"
  local code

  echo "--- ${title}"
  code="$(http_code "$url" "$method")"

  if [[ "$code" == "$expected_code" ]]; then
    echo "HTTP ${code} OK - ${ok_message}"
  else
    echo "HTTP ${code} WARNUNG - erwartet ${expected_code}: ${ok_message}"
    echo "URL: ${url}"
  fi
  echo
}

show_usage() {
  cat <<EOF
Verwendung:
  $0 build
  $0 deploy
  $0 publish
  $0 clean
  $0 status
  $0 rollback

Befehle:
  build      Baut React in ${BUILD_DIR}
  deploy     Kopiert dist nach ${WEB_DIR}
  publish    Führt build + deploy + Apache reload aus
  clean      Löscht dist und Vite-Cache
  status     Prüft Build, Web-Verzeichnis, Services und HTTP-Endpunkte
  rollback   Stellt den letzten veröffentlichten Stand wieder her

EOF
}

check_paths() {
  [[ -d "$PROJECT_DIR" ]] || fail "Projektordner fehlt: $PROJECT_DIR"
  [[ -d "$FRONTEND_DIR" ]] || fail "React-Ordner fehlt: $FRONTEND_DIR"
  [[ -f "${FRONTEND_DIR}/package.json" ]] || fail "package.json fehlt in: $FRONTEND_DIR"
}

prepare_dirs() {
  mkdir -p "$WEB_DIR"
  mkdir -p "$BACKUP_DIR"
  chmod 700 /root/.backups
}

run_build() {
  require_command npm
  check_paths

  log "React-Build startet"
  cd "$FRONTEND_DIR"

  if [[ ! -d "node_modules" ]]; then
    log "node_modules fehlt, führe npm install aus"
    npm install
  fi

  rm -rf .vite
  npm run build

  [[ -f "${BUILD_DIR}/index.html" ]] || fail "Build fehlgeschlagen: ${BUILD_DIR}/index.html fehlt"

  log "React-Build erfolgreich"
}

backup_current_web() {
  prepare_dirs

  if [[ -d "$WEB_DIR" ]] && [[ -n "$(find "$WEB_DIR" -mindepth 1 -maxdepth 1 2>/dev/null || true)" ]]; then
    local timestamp
    timestamp="$(date +"%Y-%m-%d_%H-%M-%S")"

    local backup_file="${BACKUP_DIR}/${APP_NAME}_published_${timestamp}.tar.gz"

    log "Sichere aktuellen Web-Stand: $backup_file"
    tar -czf "$backup_file" -C "$WEB_DIR" .
    chmod 600 "$backup_file"
  else
    log "Kein bestehender Web-Stand vorhanden"
  fi
}

cleanup_old_publish_backups() {
  log "Bereinige alte Publish-Backups, behalte letzte ${KEEP_PUBLISH_BACKUPS}"

  find "$BACKUP_DIR" -maxdepth 1 -type f -name "${APP_NAME}_published_*.tar.gz" \
    | sort -r \
    | tail -n +$((KEEP_PUBLISH_BACKUPS + 1)) \
    | while read -r old_backup; do
        log "Lösche altes Publish-Backup: $old_backup"
        rm -f "$old_backup"
      done
}

ensure_spa_fallback() {
  cat > "${WEB_DIR}/.htaccess" <<'EOF'
<IfModule mod_rewrite.c>
  RewriteEngine On

  # Build-Assets niemals auf index.html umbiegen.
  # Sonst laden Browser JS/CSS als text/html und React bleibt weiß.
  RewriteRule ^assets/ - [L]
  RewriteRule ^react/assets/ - [L]

  RewriteCond %{REQUEST_URI} !^/(api|auth|media|static)/
  RewriteCond %{REQUEST_FILENAME} !-f
  RewriteCond %{REQUEST_FILENAME} !-d
  RewriteRule ^ index.html [L]
</IfModule>

<IfModule mod_dir.c>
  DirectoryIndex index.html
</IfModule>
EOF
}

ensure_react_prefixed_assets() {
  # Einige Deploy-/Browserstände laden React historisch unter /react.
  # Wenn index.html Assets unter /react/assets referenziert, müssen diese Dateien
  # physisch existieren. Andernfalls liefert der SPA-Fallback index.html aus,
  # wodurch strikte MIME-Prüfung JS/CSS blockiert.
  if [[ -f "${WEB_DIR}/index.html" ]] && grep -qE '(["'"'"'`=]|url\()/react/assets/' "${WEB_DIR}/index.html"; then
    log "React-Asset-Basis /react erkannt, erstelle kompatible Asset-Spiegelung"
    mkdir -p "${WEB_DIR}/react/assets"
    cp -a "${WEB_DIR}/assets/." "${WEB_DIR}/react/assets/"
    cp -a "${WEB_DIR}/index.html" "${WEB_DIR}/react/index.html"
  fi
}

run_deploy() {
  check_paths
  prepare_dirs

  [[ -f "${BUILD_DIR}/index.html" ]] || fail "Kein Build gefunden. Bitte zuerst ausführen: $0 build"

  backup_current_web

  log "Veröffentliche React nach: $WEB_DIR"

  rm -rf "${WEB_DIR:?}/"*
  cp -a "${BUILD_DIR}/." "$WEB_DIR/"
  ensure_spa_fallback
  ensure_react_prefixed_assets

  chown -R "${WEB_USER}:${WEB_GROUP}" "$WEB_DIR"
  find "$WEB_DIR" -type d -exec chmod 755 {} \;
  find "$WEB_DIR" -type f -exec chmod 644 {} \;

  cleanup_old_publish_backups

  log "Deploy abgeschlossen"
}

reload_apache() {
  require_command apache2ctl
  require_command systemctl

  log "Prüfe Apache-Konfiguration"
  apache2ctl configtest

  log "Lade Apache neu"
  systemctl reload "$APACHE_SERVICE"

  log "Apache reload abgeschlossen"
}

run_publish() {
  run_build
  run_deploy
  reload_apache
  run_status
}

run_clean() {
  check_paths

  log "Bereinige React-Build-Dateien"
  cd "$FRONTEND_DIR"

  rm -rf dist
  rm -rf .vite
  rm -rf node_modules/.vite

  log "Clean abgeschlossen"
}

run_status() {
  log "Statusprüfung startet"

  echo
  echo "== Pfade =="
  echo "PROJECT_DIR:  $PROJECT_DIR"
  echo "FRONTEND_DIR: $FRONTEND_DIR"
  echo "BUILD_DIR:    $BUILD_DIR"
  echo "WEB_DIR:      $WEB_DIR"
  echo

  echo "== Build =="
  if [[ -f "${BUILD_DIR}/index.html" ]]; then
    echo "Build vorhanden:"
    ls -lah "${BUILD_DIR}/index.html"
  else
    echo "Build fehlt: ${BUILD_DIR}/index.html"
  fi
  echo

  echo "== Veröffentlichung =="
  if [[ -f "${WEB_DIR}/index.html" ]]; then
    echo "Web-Stand vorhanden:"
    ls -lah "${WEB_DIR}/index.html"
  else
    echo "Web-Stand fehlt: ${WEB_DIR}/index.html"
  fi
  echo

  echo "== Services =="
  if systemctl is-active --quiet "$APACHE_SERVICE"; then
    echo "Apache: aktiv"
  else
    echo "Apache: NICHT aktiv"
  fi

  if systemctl is-active --quiet "$API_SERVICE"; then
    echo "FastAPI: aktiv (${API_SERVICE})"
  else
    echo "FastAPI: NICHT aktiv (${API_SERVICE})"
  fi
  echo

  echo "== HTTP Checks =="
  if command -v curl >/dev/null 2>&1; then
    echo "--- React /"
    curl -k -I -s https://songstudio-react.klangneural.de/ | head -n 6 || true
    echo

    local js_asset css_asset
    js_asset="$(grep -oE '/(react/)?assets/[^" ]+\.js' "${WEB_DIR}/index.html" | head -n 1 || true)"
    css_asset="$(grep -oE '/(react/)?assets/[^" ]+\.css' "${WEB_DIR}/index.html" | head -n 1 || true)"

    if [[ -n "$js_asset" ]]; then
      echo "--- React JS ${js_asset}"
      curl -k -I -s "https://songstudio-react.klangneural.de${js_asset}" | head -n 8 || true
      echo
    fi

    if [[ -n "$css_asset" ]]; then
      echo "--- React CSS ${css_asset}"
      curl -k -I -s "https://songstudio-react.klangneural.de${css_asset}" | head -n 8 || true
      echo
    fi

    print_expected_http_check \
      "FastAPI Health local /health/ready" \
      "${API_LOCAL_BASE}/health/ready" \
      "200" \
      "FastAPI ist lokal erreichbar und die Datenbank antwortet"

    print_expected_http_check \
      "Auth /auth/me ohne Token" \
      "https://songstudio-react.klangneural.de/auth/me" \
      "401" \
      "Auth-Schutz aktiv, 401 ohne Login ist korrekt"

    print_expected_http_check \
      "API /api/credits ohne Token" \
      "https://songstudio-react.klangneural.de/api/credits" \
      "401" \
      "API-Schutz aktiv, 401 ohne Login ist korrekt"
  else
    echo "curl nicht installiert"
  fi

  log "Statusprüfung abgeschlossen"
}

run_rollback() {
  prepare_dirs

  local latest_backup
  latest_backup="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${APP_NAME}_published_*.tar.gz" | sort -r | head -n 1 || true)"

  [[ -n "$latest_backup" ]] || fail "Kein Publish-Backup gefunden in: $BACKUP_DIR"

  log "Rollback auf: $latest_backup"

  rm -rf "${WEB_DIR:?}/"*
  tar -xzf "$latest_backup" -C "$WEB_DIR"

  chown -R "${WEB_USER}:${WEB_GROUP}" "$WEB_DIR"
  find "$WEB_DIR" -type d -exec chmod 755 {} \;
  find "$WEB_DIR" -type f -exec chmod 644 {} \;

  reload_apache

  log "Rollback abgeschlossen"
}

main() {
  local command="${1:-}"

  require_command find
  require_command tar

  case "$command" in
    build)
      run_build
      ;;
    deploy)
      run_deploy
      ;;
    publish)
      run_publish
      ;;
    clean)
      run_clean
      ;;
    status)
      run_status
      ;;
    rollback)
      run_rollback
      ;;
    help|-h|--help|"")
      show_usage
      ;;
    *)
      show_usage
      fail "Unbekannter Befehl: $command"
      ;;
  esac
}

main "$@"

