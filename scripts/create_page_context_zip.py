#!/usr/bin/env python3.12

"""
Erzeugt schlanke Kontext-ZIP-Archive fuer einzelne React-Seitenprofile.

Ziel:
- Nur die wirklich relevanten Projektdateien fuer eine Frontendseite packen.
- Relative Originalpfade im ZIP beibehalten, z. B. app/config.py oder
  frontend-react/src/pages/DawPage.jsx.
- Geeignet fuer externe KI-Code-Reviews, Patch-Erstellung oder gezielte
  Weiterentwicklung ohne komplettes Repository und ohne Media-/Storage-Ballast.

Beispiele:
  python3 scripts/create_page_context_zip.py --page /daw
  python3 scripts/create_page_context_zip.py --page /library
  python3 scripts/create_page_context_zip.py --page /music --include-tests
  python3 scripts/create_page_context_zip.py --page /daw --include-db --dry-run
  python3 scripts/create_page_context_zip.py --page /daw --page /library --output _work/AI_CONTEXT/daw_library.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCRIPT_NAME = "create_page_context_zip.py"
DEFAULT_OUTPUT_DIR = Path("_work") / "AI_CONTEXT"
DEFAULT_DB_FILES = (
    "suno_fastapi_app.db",
)

# ---------------------------------------------------------------------------
# Gemeinsame Basisdateien
# ---------------------------------------------------------------------------

COMMON_FRONTEND_FILES = (
    "frontend-react/package.json",
    "frontend-react/package-lock.json",
    "frontend-react/vite.config.js",
    "frontend-react/index.html",
    "frontend-react/.env.production",
    "frontend-react/src/main.jsx",
    "frontend-react/src/App.jsx",
    "frontend-react/src/api/client.js",
    "frontend-react/src/utils.js",
    "frontend-react/src/styles.css",
    "frontend-react/src/styles/app.css",
    "frontend-react/src/i18n/I18nContext.jsx",
    "frontend-react/src/i18n/de.js",
    "frontend-react/src/i18n/en.js",
    "frontend-react/src/components/Login.jsx",
    "frontend-react/src/components/MiniPlayer.jsx",
    "frontend-react/src/components/Toast.jsx",
    "frontend-react/src/components/StatusDetailModal.jsx",
    "frontend-react/src/components/Modal.jsx",
    "frontend-react/src/components/ProfileMenu.jsx",
    "frontend-react/src/components/FormattedMessage.jsx",
    "frontend-react/src/components/GlobalAIAssistant.jsx",
    "frontend-react/src/context/AppAssistantContext.jsx",
    "frontend-react/src/assistant/assistantActions.js",
)

COMMON_BACKEND_FILES = (
    "requirements.txt",
    "requirements-daw-analysis.txt",
    ".env.example",
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/database.py",
    "app/models.py",
    "app/schemas.py",
    "app/auth.py",
    "app/security.py",
    "app/middleware.py",
    "app/suno_client.py",
    "app/routers/__init__.py",
    "app/services/__init__.py",
    "app/utils/__init__.py",
    "app/utils/time_utils.py",
)

# ---------------------------------------------------------------------------
# Seitenprofile
# ---------------------------------------------------------------------------

DAW_FRONTEND_FILES = (
    "frontend-react/src/pages/DawPage.jsx",
    "frontend-react/src/components/Waveform.jsx",
)

DAW_BACKEND_FILES = (
    "app/routers/daw.py",
    "app/routers/archive.py",
    "app/routers/music.py",
    "app/services/daw_beatgrid_service.py",
    "app/services/waveform_service.py",
    "app/services/audio_metadata_service.py",
    "app/services/portable_path_service.py",
    "app/services/background_task_runner.py",
    "app/services/task_lifecycle_service.py",
    "app/services/audio_asset_repair_service.py",
    "app/services/action_status_fallback_service.py",
    "app/services/ai_chat_service.py",
    "app/services/music_service.py",
    "app/services/audio_cache_service.py",
    "app/services/system_status_notification_service.py",
    "app/services/suno_song_import_service.py",
    "app/services/song_library_sync_service.py",
    "app/services/opencli_provider_service.py",
    "app/services/extend_continue_at_analysis_service.py",
)

DAW_TEST_FILES = (
    "tests/test_waveform_structure_and_sanitizing.py",
    "tests/test_frontend_source_regressions.py",
    "tests/test_action_status_fallback_service.py",
)

LIBRARY_FRONTEND_FILES = (
    "frontend-react/src/pages/LibraryPage.jsx",
    "frontend-react/src/components/EmptyState.jsx",
    "frontend-react/src/components/SectionHeader.jsx",
    "frontend-react/src/components/Waveform.jsx",
)

LIBRARY_BACKEND_FILES = (
    "app/routers/archive.py",
    "app/routers/audio_assets.py",
    "app/routers/library.py",
    "app/routers/music.py",
    "app/routers/production.py",
    "app/services/audio_metadata_service.py",
    "app/services/waveform_service.py",
    "app/services/audio_asset_repair_service.py",
    "app/services/asset_capabilities.py",
    "app/services/audio_cache_service.py",
    "app/services/audio_asset_materialization_service.py",
    "app/services/audio_ai_analysis_service.py",
    "app/services/library_ai_tagging_service.py",
    "app/services/library_content_cache_service.py",
    "app/services/video_asset_service.py",
    "app/services/extend_continue_at_analysis_service.py",
    "app/services/replicate_cover_service.py",
    "app/services/system_status_notification_service.py",
    "app/services/background_task_runner.py",
    "app/services/task_lifecycle_service.py",
    "app/services/forced_alignment_service.py",
    "app/services/srt_transcript_service.py",
    "app/services/srt_parser.py",
    "app/services/srt_export.py",
    "app/services/srt_validation.py",
    "app/services/id3_tag_service.py",
    "app/services/portable_path_service.py",
    "app/services/music_service.py",
    "app/services/suno_song_import_service.py",
    "app/services/song_library_sync_service.py",
    "app/services/opencli_provider_service.py",
)

LIBRARY_TEST_FILES = (
    "tests/test_archive_audio_helpers.py",
    "tests/test_audio_asset_schema.py",
    "tests/test_audio_assets_helper_utils.py",
    "tests/test_frontend_source_regressions.py",
    "tests/test_library_content_cache_service.py",
    "tests/test_library_delete_orphan_import_links.py",
    "tests/test_library_status_notifications.py",
    "tests/test_srt_cleanup_detail_refresh_contract.py",
    "tests/test_waveform_structure_and_sanitizing.py",
)

MUSIC_FRONTEND_FILES = (
    "frontend-react/src/pages/MusicPage.jsx",
    "frontend-react/src/components/SectionHeader.jsx",
)

MUSIC_BACKEND_FILES = (
    "app/routers/music.py",
    "app/routers/assistant.py",
    "app/routers/files.py",
    "app/routers/audio.py",
    "app/routers/lyrics.py",
    "app/routers/archive.py",
    "app/routers/audio_assets.py",
    "app/services/music_service.py",
    "app/services/opencli_provider_service.py",
    "app/services/suno_song_import_service.py",
    "app/services/song_library_sync_service.py",
    "app/services/system_status_notification_service.py",
    "app/services/background_task_runner.py",
    "app/services/task_lifecycle_service.py",
    "app/services/extend_continue_at_analysis_service.py",
    "app/services/file_service.py",
    "app/services/global_assistant_service.py",
    "app/services/ai_chat_service.py",
    "app/services/audio_cache_service.py",
    "app/services/audio_metadata_service.py",
    "app/services/audio_asset_repair_service.py",
    "app/services/asset_capabilities.py",
    "app/services/video_asset_service.py",
    "app/services/portable_path_service.py",
)

MUSIC_TEST_FILES = (
    "tests/test_music_service_generate_payload.py",
    "tests/test_schema_request_models.py",
    "tests/test_style_generation_endpoint_runtime.py",
    "tests/test_style_generation_settings_contract.py",
    "tests/test_ai_chat.py",
    "tests/test_ai_chat_service_parsing.py",
    "tests/test_audio_cache_service_db.py",
)

PROFILE_FILES = {
    "daw": {
        "route": "/daw",
        "description": "Mini-DAW, Beatgrid, Arrangement, Preview/Render und Waveform.",
        "frontend": DAW_FRONTEND_FILES,
        "backend": DAW_BACKEND_FILES,
        "tests": DAW_TEST_FILES,
    },
    "library": {
        "route": "/library",
        "description": "Audio-Library, Detailansicht, SRT, Stems, WAV, MP4, Bundle, Follow-up-Aktionen.",
        "frontend": LIBRARY_FRONTEND_FILES,
        "backend": LIBRARY_BACKEND_FILES,
        "tests": LIBRARY_TEST_FILES,
    },
    "music": {
        "route": "/music",
        "description": "Musik-Erzeugung, Style/Lyrics-Assistent, Upload/Extend/Cover/Stems/WAV/Video/Mashup.",
        "frontend": MUSIC_FRONTEND_FILES,
        "backend": MUSIC_BACKEND_FILES,
        "tests": MUSIC_TEST_FILES,
    },
}

# Optionaler Modus, falls ein KI-Chat die komplette App-Routing-Datei wirklich
# buildbar analysieren soll. Standard bleibt fokussiert und schlank.
APP_ROUTE_PAGE_IMPORTS = (
    "frontend-react/src/pages/HomePage.jsx",
    "frontend-react/src/pages/HelpPage.jsx",
    "frontend-react/src/pages/LibraryTextPage.jsx",
    "frontend-react/src/pages/LyricsStudioPage.jsx",
    "frontend-react/src/pages/PlaylistsPage.jsx",
    "frontend-react/src/pages/StylesPage.jsx",
    "frontend-react/src/pages/AdminPage.jsx",
    "frontend-react/src/pages/SystemPage.jsx",
    "frontend-react/src/pages/StatusPage.jsx",
    "frontend-react/src/pages/TrashPage.jsx",
    "frontend-react/src/pages/ImportPage.jsx",
    "frontend-react/src/pages/ProductionPage.jsx",
)


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    size: int
    sha256: str


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent

    candidates = [current, *current.parents]
    for candidate in candidates:
        if (candidate / "app" / "main.py").is_file() and (candidate / "frontend-react" / "src" / "App.jsx").is_file():
            return candidate

    raise SystemExit(
        "Projektwurzel nicht gefunden. Bitte aus dem Repository ausfuehren oder --root /pfad/zum/projekt setzen."
    )


def normalize_page(value: str) -> str:
    normalized = value.strip().lower().replace("\\", "/")
    normalized = normalized.removeprefix("/react/").removeprefix("react/")
    normalized = normalized.strip("/")
    aliases = {
        "daw": "daw",
        "library": "library",
        "music": "music",
    }
    if normalized not in aliases:
        allowed = ", ".join(f"/{name}" for name in sorted(PROFILE_FILES))
        raise argparse.ArgumentTypeError(f"Unbekanntes Profil '{value}'. Erlaubt: {allowed}")
    return aliases[normalized]


def unique_preserve_order(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in paths:
        rel = str(raw).replace("\\", "/").strip().lstrip("/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        result.append(rel)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(
    pages: list[str],
    include_backend: bool,
    include_frontend: bool,
    include_tests: bool,
    include_db: bool,
    include_app_route_imports: bool,
    extras: list[str],
) -> list[str]:
    files: list[str] = []

    if include_frontend:
        files.extend(COMMON_FRONTEND_FILES)
        if include_app_route_imports:
            files.extend(APP_ROUTE_PAGE_IMPORTS)

    if include_backend:
        files.extend(COMMON_BACKEND_FILES)

    for page in pages:
        profile = PROFILE_FILES[page]
        if include_frontend:
            files.extend(profile["frontend"])
        if include_backend:
            files.extend(profile["backend"])
        if include_tests:
            files.extend(profile["tests"])

    if include_db:
        files.extend(DEFAULT_DB_FILES)

    files.extend(extras)
    return unique_preserve_order(files)


def resolve_existing_files(root: Path, rel_paths: list[str]) -> tuple[list[FileEntry], list[str]]:
    entries: list[FileEntry] = []
    missing: list[str] = []

    for rel_path in rel_paths:
        path = root / rel_path
        if path.is_file():
            entries.append(FileEntry(rel_path=rel_path, size=path.stat().st_size, sha256=sha256_file(path)))
        else:
            missing.append(rel_path)

    return entries, missing


def default_output_path(pages: list[str], root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page_part = "_".join(pages)
    return root / DEFAULT_OUTPUT_DIR / f"{stamp}_{page_part}_context.zip"


def build_manifest(
    pages: list[str],
    root: Path,
    entries: list[FileEntry],
    missing: list[str],
    args: argparse.Namespace,
) -> dict:
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": f"scripts/{SCRIPT_NAME}",
        "project_root": str(root),
        "profiles": [
            {
                "name": page,
                "route": PROFILE_FILES[page]["route"],
                "description": PROFILE_FILES[page]["description"],
            }
            for page in pages
        ],
        "options": {
            "include_frontend": args.include_frontend,
            "include_backend": args.include_backend,
            "include_tests": args.include_tests,
            "include_db": args.include_db,
            "include_app_route_imports": args.include_app_route_imports,
            "strict": args.strict,
        },
        "file_count": len(entries),
        "total_bytes": sum(entry.size for entry in entries),
        "missing_files": missing,
        "files": [entry.__dict__ for entry in entries],
    }


def build_markdown_summary(manifest: dict) -> str:
    profile_names = ", ".join(item["route"] for item in manifest["profiles"])
    lines = [
        "# KI-Kontext-ZIP Manifest",
        "",
        f"- Profile: `{profile_names}`",
        f"- Erstellt UTC: `{manifest['created_at_utc']}`",
        f"- Dateien: `{manifest['file_count']}`",
        f"- Gesamtgroesse: `{manifest['total_bytes']}` Bytes",
        f"- SQLite enthalten: `{manifest['options']['include_db']}`",
        f"- Tests enthalten: `{manifest['options']['include_tests']}`",
        "",
        "## Enthaltene Dateien",
        "",
    ]
    for item in manifest["files"]:
        lines.append(f"- `{item['rel_path']}` ({item['size']} Bytes, SHA256 `{item['sha256']}`)")
    if manifest["missing_files"]:
        lines.extend(["", "## Fehlende Dateien", ""])
        for rel_path in manifest["missing_files"]:
            lines.append(f"- `{rel_path}`")
    lines.append("")
    return "\n".join(lines)


def write_zip(root: Path, output_path: Path, entries: list[FileEntry], manifest: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in entries:
            archive.write(root / entry.rel_path, arcname=entry.rel_path)
        archive.writestr("AI_CONTEXT_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("AI_CONTEXT_MANIFEST.md", build_markdown_summary(manifest))


def list_profiles() -> None:
    print("Verfuegbare Profile:")
    for name, profile in PROFILE_FILES.items():
        print(f"  {profile['route']:<10} {profile['description']}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erstellt ein schlankes Kontext-ZIP fuer /daw, /library oder /music mit Originalpfaden.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--page",
        action="append",
        type=normalize_page,
        choices=sorted(PROFILE_FILES),
        help="Seitenprofil. Mehrfach verwendbar. Erlaubt: /daw, /library, /music.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Projektwurzel. Standard: automatische Erkennung aus dem aktuellen Pfad.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ziel-ZIP. Standard: _work/AI_CONTEXT/<timestamp>_<profile>_context.zip",
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="Nur Frontend-Dateien packen.",
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Nur Backend-Dateien packen.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Profilnahe Tests mitpacken.",
    )
    parser.add_argument(
        "--include-db",
        action="store_true",
        help="SQLite-Datenbank mitpacken. Nur nutzen, wenn echte lokale Daten benoetigt werden.",
    )
    parser.add_argument(
        "--include-app-route-imports",
        action="store_true",
        help="Alle von App.jsx direkt importierten Seiten mitpacken. Macht das ZIP groesser, aber routing-naher.",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Zusaetzliche Datei relativ zur Projektwurzel. Mehrfach verwendbar.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Bei fehlenden Dateien mit Fehler abbrechen.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur Dateiliste anzeigen, kein ZIP schreiben.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Verfuegbare Profile anzeigen und beenden.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.list_profiles:
        list_profiles()
        return 0

    if args.frontend_only and args.backend_only:
        print("FEHLER: --frontend-only und --backend-only koennen nicht gleichzeitig verwendet werden.", file=sys.stderr)
        return 2

    pages = unique_preserve_order(args.page or [])
    if not pages:
        print("FEHLER: Bitte mindestens ein Profil mit --page /daw, --page /library oder --page /music angeben.", file=sys.stderr)
        return 2

    root = find_project_root(args.root or Path.cwd())
    include_frontend = not args.backend_only
    include_backend = not args.frontend_only
    args.include_frontend = include_frontend
    args.include_backend = include_backend

    rel_paths = collect_files(
        pages=pages,
        include_backend=include_backend,
        include_frontend=include_frontend,
        include_tests=args.include_tests,
        include_db=args.include_db,
        include_app_route_imports=args.include_app_route_imports,
        extras=args.extra,
    )
    entries, missing = resolve_existing_files(root, rel_paths)

    if missing:
        print("WARNUNG: Fehlende Dateien:", file=sys.stderr)
        for rel_path in missing:
            print(f"  - {rel_path}", file=sys.stderr)
        if args.strict:
            print("Abbruch wegen --strict.", file=sys.stderr)
            return 1

    output_path = (args.output if args.output else default_output_path(pages, root))
    if not output_path.is_absolute():
        output_path = root / output_path

    manifest = build_manifest(pages, root, entries, missing, args)

    print(f"Projektwurzel: {root}")
    print(f"Profile: {', '.join('/' + page for page in pages)}")
    print(f"Dateien: {len(entries)}")
    print(f"Groesse: {sum(entry.size for entry in entries)} Bytes")
    print("")
    for entry in entries:
        print(entry.rel_path)

    if args.dry_run:
        print("\nDry-run aktiv: kein ZIP geschrieben.")
        return 0

    if not entries:
        print("FEHLER: Keine Dateien gefunden.", file=sys.stderr)
        return 1

    write_zip(root, output_path, entries, manifest)
    print(f"\nZIP erstellt: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
