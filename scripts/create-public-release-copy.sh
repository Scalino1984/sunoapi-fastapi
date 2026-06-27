#!/usr/bin/env bash
set -euo pipefail

# Zielkonfiguration:
# Standard ist ~/.public-apps/<ordnername-des-projektstamms>.
# Bei Bedarf nur diese Werte ueberschreiben, z. B.:
#   PUBLIC_TARGET_DIR="$HOME/.public-apps/songstudio-public" ./scripts/create-public-release-copy.sh
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="${PROJECT_NAME:-$(basename "$SOURCE_ROOT")}"
PUBLIC_APPS_ROOT="${PUBLIC_APPS_ROOT:-$HOME/.public-apps}"
PUBLIC_TARGET_DIR="${PUBLIC_TARGET_DIR:-$PUBLIC_APPS_ROOT/$PROJECT_NAME}"

# Verwendet docs/github/README.md als README.md in der Zielkopie.
USE_GITHUB_README="${USE_GITHUB_README:-true}"

# Synchronisiert den Zielordner exakt. Der Sicherheitscheck unten erlaubt das
# nur innerhalb von PUBLIC_APPS_ROOT.
RSYNC_DELETE="${RSYNC_DELETE:-true}"

DRY_RUN="false"
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN="true"
      ;;
    --no-delete)
      RSYNC_DELETE="false"
      ;;
    -h|--help)
      cat <<'HELP'
Erstellt eine bereinigte Veroeffentlichungs-Kopie dieses Projekts.

Zielpfad:
  Standard: ~/.public-apps/<ordnername-des-stammordners>
  Override: PUBLIC_TARGET_DIR="$HOME/.public-apps/songstudio-public" ./scripts/create-public-release-copy.sh

Optionen:
  --dry-run     Zeigt, was kopiert wuerde, ohne Dateien zu schreiben.
  --no-delete   Loescht keine veralteten Dateien im Zielordner.

Ausgeschlossen werden u. a.:
  .env, .env.*, .git, node_modules, venv/.venv, lokale DBs, Runtime-Logs,
  Test-Caches, Storage-Inhalte, generierte Audio-/Cover-/Video-Dateien.
HELP
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $arg" >&2
      exit 2
      ;;
  esac
done

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync ist erforderlich, wurde aber nicht gefunden." >&2
  exit 1
fi

public_root_abs="$(realpath -m "$PUBLIC_APPS_ROOT")"
target_abs="$(realpath -m "$PUBLIC_TARGET_DIR")"
source_abs="$(realpath -m "$SOURCE_ROOT")"

case "$target_abs" in
  "$public_root_abs"/*) ;;
  *)
    echo "Abbruch: Ziel liegt nicht unter PUBLIC_APPS_ROOT." >&2
    echo "PUBLIC_APPS_ROOT: $public_root_abs" >&2
    echo "Ziel:             $target_abs" >&2
    exit 1
    ;;
esac

if [[ "$target_abs" == "$source_abs" ]]; then
  echo "Abbruch: Ziel darf nicht identisch mit SOURCE_ROOT sein." >&2
  exit 1
fi

if [[ "$target_abs" == "/" || -z "$target_abs" ]]; then
  echo "Abbruch: unsicherer Zielpfad." >&2
  exit 1
fi

rsync_destination="$target_abs/"
dry_tmp_root=""
if [[ "$DRY_RUN" == "true" && ! -d "$public_root_abs" ]]; then
  dry_tmp_root="$(mktemp -d /tmp/public-release-copy-dry-run.XXXXXX)"
  trap '[[ -n "${dry_tmp_root:-}" ]] && rm -rf "$dry_tmp_root"' EXIT
  rsync_destination="$dry_tmp_root/$PROJECT_NAME/"
  echo "Dry-Run Hinweis: $public_root_abs existiert nicht. Rsync nutzt temporaer $rsync_destination"
elif [[ "$DRY_RUN" != "true" ]]; then
  mkdir -p "$public_root_abs"
fi

rsync_args=(
  -a
  --human-readable
  --info=stats2,name1
)

if [[ "$RSYNC_DELETE" == "true" ]]; then
  rsync_args+=(--delete --delete-excluded)
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
  --exclude="frontend-react/dist/"
  --exclude="storage/"
  --exclude="covers/"
  --exclude="documentation/"
  --exclude="documentation/test-audit-logs/"
  --exclude="documentation/local_audiofiles.txt"
  --exclude="documentation/storage_snapshot.txt"
  --exclude="documentation/tree-list-storage.txt"
  --exclude="PATCH_*.md"
  --exclude="RELEASE_*.md"
  --exclude="TECH_*.md"
  --exclude="SYSTEMANWEISUNG_*.md"
  --exclude="KI_FUNKTIONEN_*.md"
  --exclude="POSTGRESQL_UMSTELLUNG_*.md"
  --exclude="UMSETZUNGSPLAN_*.md"
  --exclude="FINALISIERTER_*.md"
  --exclude="CURRENT_SNAPSHOT_*.md"
  --exclude="PROJECT_BASELINE_*.md"
  --exclude="CODEBASE_ANALYSE.md"
  --exclude="DATABASE_SCHEMA_OVERVIEW_AI_AGENTS.md"
  --exclude="README_*.md"
  --exclude="GIT-README.md"
  --exclude="*.patch"
  --exclude="*.bck"
  --exclude="*.backup"
  --exclude="catalog.csv"
  --exclude="songabfrage.txt"
  --exclude="srt_reference_script_logic_patch_sha256.txt"
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
  --exclude="cover_*.jpg"
  --exclude="cover_*.jpeg"
  --exclude="cover_*.png"
  --exclude="input*.png"
  --exclude="referenz.png"
  --exclude="palette.png"
)

echo "Quelle: $source_abs"
echo "Ziel:   $target_abs"
echo "DryRun: $DRY_RUN"
echo "Delete: $RSYNC_DELETE"

rsync "${rsync_args[@]}" "${exclude_args[@]}" "$source_abs/" "$rsync_destination"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry-Run abgeschlossen. Es wurden keine Dateien geschrieben."
  exit 0
fi

mkdir -p \
  "$target_abs/storage/audio" \
  "$target_abs/storage/covers" \
  "$target_abs/storage/transcripts" \
  "$target_abs/storage/backups" \
  "$target_abs/storage/stems"

for dir in \
  "$target_abs/storage/audio" \
  "$target_abs/storage/covers" \
  "$target_abs/storage/transcripts" \
  "$target_abs/storage/backups" \
  "$target_abs/storage/stems"; do
  : > "$dir/.gitkeep"
done

if [[ "$USE_GITHUB_README" == "true" && -f "$source_abs/docs/github/README.md" ]]; then
  cp "$source_abs/docs/github/README.md" "$target_abs/README.md"
fi

cat > "$target_abs/PUBLIC_COPY_MANIFEST.txt" <<MANIFEST
Public release copy
Created: $(date -Iseconds)
Source:  $source_abs
Target:  $target_abs

Excluded: real .env files, local databases, node_modules, venv/.venv,
runtime files, pytest caches, storage content, generated audio/video/media,
private test runtime content and git metadata.

Note: Verify README, screenshots, license and .env.example before publishing.
MANIFEST

echo "Fertig: $target_abs"
echo "README fuer GitHub: $target_abs/README.md"
