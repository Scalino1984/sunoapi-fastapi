#!/usr/bin/env bash
set -euo pipefail

# GitHub-Repository-Verwaltung fuer dieses Projekt.
#
# Ziele:
# - schnelle Status-/Remote-/Repo-Pruefung
# - README-Bildlinks und einfache Secret-Muster pruefen
# - Push/Pull-Funktionen aus einem zentralen Script
# - gefaehrliche Repo-Aenderungen nur mit --apply/-a ausfuehren

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_REPO_FULL_NAME="${DEFAULT_REPO_FULL_NAME:-Scalino1984/sunoapi-fastapi}"
REPO_FULL_NAME="${REPO_FULL_NAME:-$DEFAULT_REPO_FULL_NAME}"
DEFAULT_VISIBILITY="${DEFAULT_VISIBILITY:-private}"

APPLY="false"
OPEN_BROWSER="false"
COMMAND="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

show_usage() {
  cat <<'HELP'
Verwaltet das GitHub-Repository dieses Projekts.

Standard:
  REPO_FULL_NAME=Scalino1984/sunoapi-fastapi

Beispiele:
  scripts/github-repo-manager.sh status
  scripts/github-repo-manager.sh info
  scripts/github-repo-manager.sh release-check
  scripts/github-repo-manager.sh push
  scripts/github-repo-manager.sh set-public --apply
  scripts/github-repo-manager.sh set-private -a
  scripts/github-repo-manager.sh open

Kommandos:
  status             Lokaler Git-Status + GitHub-Repo-Kurzinfo.
  info               Ausfuehrlichere GitHub-Repo-Info anzeigen.
  open               Repository im Browser oeffnen.
  readme-links       README-Bildlinks pruefen.
  secret-scan        Einfache Token-/Secret-Muster in getrackten Dateien suchen.
  release-check      readme-links + secret-scan + Git-Status.
  push               Aktuellen Branch zu origin pushen.
  pull               Aktuellen Branch per ff-only pullen.
  sync               Erst pull --ff-only, dann push.
  set-private        Repo auf privat setzen. Nur mit --apply/-a.
  set-public         Repo auf oeffentlich setzen. Nur mit --apply/-a.
  ensure-remote      Origin auf GitHub-Repo setzen, falls origin fehlt.
  ensure-repo        GitHub-Repo erstellen, falls es fehlt. Nur mit --apply/-a.
  help               Diese Hilfe anzeigen.

Optionen:
  --apply, -a        Aenderungen wirklich ausfuehren. Ohne diese Option Dry-Run
                     fuer Repo-Aenderungen wie set-public/set-private/ensure-repo.
  --repo, -R NAME    Repository in owner/name-Form ueberschreiben.
  --web, -w          Bei info/status zusaetzlich Browser oeffnen.
  --help, -h         Hilfe anzeigen.

Variablen:
  REPO_FULL_NAME=owner/name
  DEFAULT_VISIBILITY=private|public
HELP
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply|-a)
      APPLY="true"
      shift
      ;;
    --repo|-R)
      REPO_FULL_NAME="${2:-}"
      [[ -n "$REPO_FULL_NAME" ]] || { echo "FEHLER: --repo/-R braucht einen Wert." >&2; exit 2; }
      shift 2
      ;;
    --repo=*|-R=*)
      REPO_FULL_NAME="${1#*=}"
      shift
      ;;
    --web|-w)
      OPEN_BROWSER="true"
      shift
      ;;
    --help|-h)
      show_usage
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $1" >&2
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

repo_url() {
  printf 'https://github.com/%s.git' "$REPO_FULL_NAME"
}

repo_page_url() {
  printf 'https://github.com/%s' "$REPO_FULL_NAME"
}

current_branch() {
  git -C "$SOURCE_ROOT" branch --show-current
}

ensure_git_repo() {
  git -C "$SOURCE_ROOT" rev-parse --show-toplevel >/dev/null 2>&1 || fail "Kein Git-Repository: $SOURCE_ROOT"
}

github_repo_exists() {
  gh repo view "$REPO_FULL_NAME" >/dev/null 2>&1
}

print_local_status() {
  echo "Projekt:  $SOURCE_ROOT"
  echo "Repo:     $REPO_FULL_NAME"
  echo "Branch:   $(current_branch)"
  echo
  git -C "$SOURCE_ROOT" status -sb
  echo
  git -C "$SOURCE_ROOT" remote -v || true
}

cmd_status() {
  require_command git
  require_command gh
  ensure_git_repo
  print_local_status
  echo
  if github_repo_exists; then
    gh repo view "$REPO_FULL_NAME" --json nameWithOwner,visibility,url,defaultBranchRef,description
  else
    echo "GitHub-Repo existiert nicht oder ist nicht erreichbar: $REPO_FULL_NAME"
  fi
  if [[ "$OPEN_BROWSER" == "true" ]]; then
    gh repo view "$REPO_FULL_NAME" --web
  fi
}

cmd_info() {
  require_command gh
  if ! github_repo_exists; then
    fail "GitHub-Repo existiert nicht oder ist nicht erreichbar: $REPO_FULL_NAME"
  fi
  gh repo view "$REPO_FULL_NAME" --json nameWithOwner,visibility,url,defaultBranchRef,description,createdAt,updatedAt,isPrivate
  if [[ "$OPEN_BROWSER" == "true" ]]; then
    gh repo view "$REPO_FULL_NAME" --web
  fi
}

cmd_open() {
  require_command gh
  gh repo view "$REPO_FULL_NAME" --web
}

cmd_readme_links() {
  require_command python3
  python3 - "$SOURCE_ROOT" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
readme = root / "README.md"
text = readme.read_text(encoding="utf-8")
paths = re.findall(r"\((documentation/images/[^)]+)\)", text)
missing = [path for path in paths if not (root / path).exists()]
print(f"README image links: {len(paths)} total, {len(set(paths))} unique, {len(missing)} missing")
for path in missing:
    print(f"MISSING {path}")
sys.exit(1 if missing else 0)
PY
}

cmd_secret_scan() {
  require_command git
  require_command rg
  ensure_git_repo
  echo "Scanne getrackte Dateien auf typische Token-Muster..."
  if (
    cd "$SOURCE_ROOT"
    git ls-files -z \
      | xargs -0 rg -n --pcre2 "(?<![A-Za-z0-9_])(ghp_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})" 2>/dev/null
  ); then
    fail "Moegliche Secrets gefunden. Ausgabe oben pruefen."
  fi
  echo "Keine typischen Token-Muster gefunden."
}

cmd_release_check() {
  cmd_readme_links
  cmd_secret_scan
  echo
  print_local_status
}

cmd_push() {
  require_command git
  ensure_git_repo
  local branch
  branch="$(current_branch)"
  [[ -n "$branch" ]] || fail "Kein aktiver Branch."
  git -C "$SOURCE_ROOT" push -u origin "$branch"
}

cmd_pull() {
  require_command git
  ensure_git_repo
  git -C "$SOURCE_ROOT" pull --ff-only
}

cmd_sync() {
  cmd_pull
  cmd_push
}

cmd_set_visibility() {
  require_command gh
  local visibility="$1"
  if [[ "$APPLY" != "true" ]]; then
    echo "Dry-Run: wuerde $REPO_FULL_NAME auf '$visibility' setzen."
    echo "Zum Ausfuehren: scripts/github-repo-manager.sh set-$visibility --apply"
    return 0
  fi
  gh repo edit "$REPO_FULL_NAME" --visibility "$visibility"
  gh repo view "$REPO_FULL_NAME" --json nameWithOwner,visibility,url
}

cmd_ensure_remote() {
  require_command git
  ensure_git_repo
  local url
  url="$(repo_url)"
  if git -C "$SOURCE_ROOT" remote get-url origin >/dev/null 2>&1; then
    echo "origin existiert bereits:"
    git -C "$SOURCE_ROOT" remote -v
    return 0
  fi
  git -C "$SOURCE_ROOT" remote add origin "$url"
  git -C "$SOURCE_ROOT" remote -v
}

cmd_ensure_repo() {
  require_command gh
  if github_repo_exists; then
    echo "GitHub-Repo existiert bereits: $(repo_page_url)"
    return 0
  fi
  if [[ "$APPLY" != "true" ]]; then
    echo "Dry-Run: wuerde GitHub-Repo erstellen: $REPO_FULL_NAME ($DEFAULT_VISIBILITY)"
    echo "Zum Ausfuehren: scripts/github-repo-manager.sh ensure-repo --apply"
    return 0
  fi
  local visibility_flag="--private"
  if [[ "$DEFAULT_VISIBILITY" == "public" ]]; then
    visibility_flag="--public"
  fi
  gh repo create "$REPO_FULL_NAME" "$visibility_flag" --source="$SOURCE_ROOT" --remote=origin
}

case "$COMMAND" in
  status)
    cmd_status
    ;;
  info)
    cmd_info
    ;;
  open)
    cmd_open
    ;;
  readme-links)
    cmd_readme_links
    ;;
  secret-scan)
    cmd_secret_scan
    ;;
  release-check)
    cmd_release_check
    ;;
  push)
    cmd_push
    ;;
  pull)
    cmd_pull
    ;;
  sync)
    cmd_sync
    ;;
  set-private)
    cmd_set_visibility private
    ;;
  set-public)
    cmd_set_visibility public
    ;;
  ensure-remote)
    cmd_ensure_remote
    ;;
  ensure-repo)
    cmd_ensure_repo
    ;;
  help|--help|-h)
    show_usage
    ;;
  *)
    echo "Unbekanntes Kommando: $COMMAND" >&2
    show_usage >&2
    exit 2
    ;;
esac
