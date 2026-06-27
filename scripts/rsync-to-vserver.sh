#!/usr/bin/env bash
set -euo pipefail

# VServer-Rsync-Deploy fuer SongStudio.
# Standardziel laut aktueller Serverstruktur:
#   ssh -i /home/astier/.ssh/id_ionos root@server.klangneural.de
#   /opt/songstudio
#
# Sicherheit:
# - Standard ist DRY-RUN. Erst --apply kopiert wirklich.
# - Echte .env, lokale DBs, storage/, venv/.venv, node_modules und Runtime-Daten
#   werden weder hochgeladen noch per --delete auf dem Server geloescht.
# - --delete entfernt nur nicht ausgeschlossene Projektdateien, die lokal nicht
#   mehr existieren. Ausgeschlossene Serverdaten bleiben erhalten.

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SSH_KEY="${SSH_KEY:-/home/astier/.ssh/id_ionos}"
SSH_TARGET="${SSH_TARGET:-root@server.klangneural.de}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/opt/songstudio}"

REMOTE_SERVICE_NAME="${REMOTE_SERVICE_NAME:-songstudio-vanilla.service}"
REMOTE_REACT_BUILD_CMD="${REMOTE_REACT_BUILD_CMD:-npm run react:build}"
REMOTE_REACT_PUBLISH_CMD="${REMOTE_REACT_PUBLISH_CMD:-npm run react:publish}"
REMOTE_RESTART_CMD="${REMOTE_RESTART_CMD:-systemctl restart ${REMOTE_SERVICE_NAME}}"

DRY_RUN="true"
RSYNC_DELETE="${RSYNC_DELETE:-true}"
REMOTE_MKDIR="${REMOTE_MKDIR:-true}"
RUN_REMOTE_RESTART="false"
RUN_REMOTE_REACT_BUILD="false"
RUN_REMOTE_REACT_PUBLISH="false"
RUN_REMOTE_POST_DEPLOY="false"

show_usage() {
  cat <<'HELP'
Synchronisiert aktualisierte Projektdateien per rsync auf den VServer.

Standard:
  SSH_KEY=/home/astier/.ssh/id_ionos
  SSH_TARGET=root@server.klangneural.de
  REMOTE_APP_DIR=/opt/songstudio

Beispiele:
  scripts/rsync-to-vserver.sh
  scripts/rsync-to-vserver.sh --apply
  scripts/rsync-to-vserver.sh -a
  scripts/rsync-to-vserver.sh -a -r
  scripts/rsync-to-vserver.sh -a -p -r
  scripts/rsync-to-vserver.sh -a -P

Variablen:
  SSH_KEY=/pfad/key
  SSH_TARGET=root@example.org
  REMOTE_APP_DIR=/opt/songstudio
  REMOTE_SERVICE_NAME=songstudio-vanilla.service
  REMOTE_REACT_BUILD_CMD='npm run react:build'
  REMOTE_REACT_PUBLISH_CMD='npm run react:publish'
  REMOTE_RESTART_CMD='systemctl restart songstudio-vanilla.service'
  RSYNC_DELETE=true|false

Optionen:
  --apply, -a          Wirklich kopieren. Ohne diese Option nur Dry-Run.
  --dry-run, -d        Explizit nur simulieren.
  --no-delete, -n      Keine veralteten Dateien im Ziel loeschen.
  --build-react, -b    Nach erfolgreichem Sync Remote-React-Build ausfuehren.
  --restart, -r        Nach erfolgreichem Sync Remote-Restart ausfuehren.
  --publish-react, -p  Nach erfolgreichem Sync Remote-React-Publish ausfuehren.
  --post-deploy, -P    Nach erfolgreichem Sync ausfuehren:
                       npm run react:build
                       npm run react:publish
                       systemctl restart songstudio-vanilla.service
  --help, -h           Hilfe anzeigen.
HELP
}

for arg in "$@"; do
  case "$arg" in
    --apply|-a)
      DRY_RUN="false"
      ;;
    --dry-run|-d)
      DRY_RUN="true"
      ;;
    --no-delete|-n)
      RSYNC_DELETE="false"
      ;;
    --restart|-r)
      RUN_REMOTE_RESTART="true"
      ;;
    --build-react|-b)
      RUN_REMOTE_REACT_BUILD="true"
      ;;
    --publish-react|-p)
      RUN_REMOTE_REACT_PUBLISH="true"
      ;;
    --post-deploy|-P)
      RUN_REMOTE_POST_DEPLOY="true"
      RUN_REMOTE_REACT_BUILD="true"
      RUN_REMOTE_REACT_PUBLISH="true"
      RUN_REMOTE_RESTART="true"
      ;;
    -h|--help)
      show_usage
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $arg" >&2
      show_usage >&2
      exit 2
      ;;
  esac
done

fail() {
  echo "FEHLER: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Befehl fehlt: $1"
}

quote_remote_path() {
  printf "%q" "$1"
}

require_command rsync
require_command ssh

[[ -d "$SOURCE_ROOT" ]] || fail "SOURCE_ROOT fehlt: $SOURCE_ROOT"
[[ -f "$SSH_KEY" ]] || fail "SSH_KEY fehlt: $SSH_KEY"
[[ -n "$SSH_TARGET" ]] || fail "SSH_TARGET ist leer"
[[ "$REMOTE_APP_DIR" == /* ]] || fail "REMOTE_APP_DIR muss absolut sein: $REMOTE_APP_DIR"
[[ "$REMOTE_APP_DIR" != "/" ]] || fail "REMOTE_APP_DIR darf nicht / sein"

SSH_CMD=(
  ssh
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
)

remote_dir_quoted="$(quote_remote_path "$REMOTE_APP_DIR")"

if [[ "$REMOTE_MKDIR" == "true" && "$DRY_RUN" == "false" ]]; then
  echo "Remote-Zielordner vorbereiten: $SSH_TARGET:$REMOTE_APP_DIR"
  "${SSH_CMD[@]}" "$SSH_TARGET" "mkdir -p $remote_dir_quoted"
fi

rsync_args=(
  -az
  --human-readable
  --itemize-changes
  --info=stats2
  -e "$(printf '%q ' "${SSH_CMD[@]}")"
)

if [[ "$RSYNC_DELETE" == "true" ]]; then
  rsync_args+=(--delete)
fi

if [[ "$DRY_RUN" == "true" ]]; then
  rsync_args+=(--dry-run)
fi

exclude_args=(
  --include=".env.example"
  --include="**/.env.example"
  --exclude=".env"
  --exclude=".env.*"
  --exclude="**/.env"
  --exclude="**/.env.*"
  --exclude=".git/"
  --exclude=".agents/"
  --exclude=".codex/"
  --exclude=".pytest_cache/"
  --exclude=".pytest-runtime/"
  --exclude=".runtime/"
  --exclude="__pycache__/"
  --exclude="**/__pycache__/"
  --exclude="*.pyc"
  --exclude="*.pyo"
  --exclude="*.log"
  --exclude="*.sqlite"
  --exclude="*.sqlite3"
  --exclude="*.db"
  --exclude="*.db-*"
  --exclude="venv/"
  --exclude=".venv/"
  --exclude="node_modules/"
  --exclude="**/node_modules/"
  --exclude="frontend-react/node_modules/"
  --exclude="frontend-react/dist/"
  --exclude="frontend-react/.vite/"
  --exclude="storage/"
  --exclude="covers/"
  --exclude="test-suno/"
  --exclude="*.zip"
  --exclude="*.tar"
  --exclude="*.tar.gz"
  --exclude="*.tgz"
  --exclude="*.mp3"
  --exclude="*.wav"
  --exclude="*.m4a"
  --exclude="*.flac"
  --exclude="*.aac"
  --exclude="*.ogg"
  --exclude="*.mp4"
  --exclude="*.mov"
  --exclude="*.webm"
  --exclude="*.gif"
)

echo "Quelle:        $SOURCE_ROOT"
echo "Remote:        $SSH_TARGET"
echo "Remote-Pfad:   $REMOTE_APP_DIR"
echo "Dry-Run:       $DRY_RUN"
echo "Delete:        $RSYNC_DELETE"
echo "React Build:   $RUN_REMOTE_REACT_BUILD"
echo "Restart:       $RUN_REMOTE_RESTART"
echo "React Publish: $RUN_REMOTE_REACT_PUBLISH"
echo "Post Deploy:   $RUN_REMOTE_POST_DEPLOY"
echo

rsync "${rsync_args[@]}" "${exclude_args[@]}" "$SOURCE_ROOT/" "${SSH_TARGET}:${REMOTE_APP_DIR%/}/"

if [[ "$DRY_RUN" == "true" ]]; then
  echo
  echo "Dry-Run abgeschlossen. Fuer echte Synchronisierung:"
  echo "  scripts/rsync-to-vserver.sh --apply"
  exit 0
fi

if [[ "$RUN_REMOTE_REACT_BUILD" == "true" ]]; then
  echo "Remote React-Build: $REMOTE_REACT_BUILD_CMD"
  "${SSH_CMD[@]}" "$SSH_TARGET" "cd $remote_dir_quoted && $REMOTE_REACT_BUILD_CMD"
fi

if [[ "$RUN_REMOTE_REACT_PUBLISH" == "true" ]]; then
  echo "Remote React-Publish: $REMOTE_REACT_PUBLISH_CMD"
  "${SSH_CMD[@]}" "$SSH_TARGET" "cd $remote_dir_quoted && $REMOTE_REACT_PUBLISH_CMD"
fi

if [[ "$RUN_REMOTE_RESTART" == "true" ]]; then
  echo "Remote Restart: $REMOTE_RESTART_CMD"
  "${SSH_CMD[@]}" "$SSH_TARGET" "cd $remote_dir_quoted && $REMOTE_RESTART_CMD"
fi

echo "Rsync abgeschlossen: $SSH_TARGET:$REMOTE_APP_DIR"
