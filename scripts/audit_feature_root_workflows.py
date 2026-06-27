#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

FEATURE_ORDER = [
    "SRT",
    "Stems",
    "WAV",
    "Player",
    "Download",
    "Favoriten",
    "Cover",
    "Songdetails",
    "Production",
]

CORE_TABLES = [
    "audio_assets",
    "songs",
    "suno_tasks",
    "audio_projects",
    "audio_transcripts",
    "status_notifications",
    "playlist_items",
]

VALID_ASSET_STATUSES = {
    "created",
    "cached",
    "remote",
    "failed",
    "missing",
    "deleted",
    "imported",
    "completed",
    "ready",
}

ARCHIVED_TRANSCRIPT_STATUSES = {"archived_orphan", "orphaned", "deleted_asset_archived"}

OK = "OK"
INFO = "INFO"
LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
CRITICAL = "CRITICAL"

SEVERITY_RANK = {
    OK: 0,
    INFO: 1,
    LOW: 2,
    MEDIUM: 3,
    HIGH: 4,
    CRITICAL: 5,
}


@dataclass
class Finding:
    feature: str
    severity: str
    code: str
    message: str
    count: int = 1
    sample: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "severity": self.severity,
            "code": self.code,
            "count": self.count,
            "message": self.message,
            "sample": self.sample[:10],
        }


class SafeSqlite:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.con: sqlite3.Connection | None = None
        self.columns_cache: dict[str, set[str]] = {}

    def __enter__(self) -> "SafeSqlite":
        # mode=ro verhindert versehentliche Schreibzugriffe. Ohne immutable, damit WAL/SHM konsistent gelesen werden.
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        self.con = sqlite3.connect(uri, uri=True)
        self.con.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.con is not None:
            self.con.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        if self.con is None:
            raise RuntimeError("Datenbankverbindung ist nicht geöffnet.")
        return self.con.execute(sql, tuple(params))

    def scalar(self, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
        row = self.execute(sql, params).fetchone()
        if row is None:
            return default
        return row[0]

    def rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.execute(sql, params).fetchall()]

    def table_exists(self, table: str) -> bool:
        return bool(self.scalar("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))

    def columns(self, table: str) -> set[str]:
        if table not in self.columns_cache:
            if not self.table_exists(table):
                self.columns_cache[table] = set()
            else:
                self.columns_cache[table] = {row[1] for row in self.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()}
        return self.columns_cache[table]

    def has_columns(self, table: str, *columns: str) -> bool:
        table_columns = self.columns(table)
        return all(col in table_columns for col in columns)

    def count(self, table: str, where: str = "", params: Iterable[Any] = ()) -> int:
        if not self.table_exists(table):
            return 0
        sql = f"SELECT COUNT(*) FROM {quote_identifier(table)}"
        if where:
            sql += f" WHERE {where}"
        return int(self.scalar(sql, params, 0) or 0)


# ---------- Allgemeine Helfer ----------


def quote_identifier(value: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValueError(f"Ungültiger SQL-Identifier: {value}")
    return f'"{value}"'


def project_root() -> Path:
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "scripts" else Path.cwd()


def resolve_db_path(value: str | None, root: Path) -> Path:
    raw = (value or os.environ.get("DATABASE_URL") or "sqlite:///suno_fastapi_app.db").strip()
    if raw.startswith("sqlite:///"):
        raw = raw.replace("sqlite:///", "", 1)
    elif raw.startswith("sqlite://"):
        raw = raw.replace("sqlite://", "", 1)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def json_get(value: Any, *keys: str, default: Any = None) -> Any:
    current = parse_json(value)
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def active_clause(table_alias: str | None = None) -> str:
    prefix = f"{table_alias}." if table_alias else ""
    return f"COALESCE({prefix}is_deleted, 0) = 0"


def read_text(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def file_exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def contains(root: Path, rel: str, needle: str) -> bool:
    return needle in read_text(root, rel)


def regex_count(root: Path, rel: str, pattern: str) -> int:
    return len(re.findall(pattern, read_text(root, rel), flags=re.MULTILINE | re.DOTALL))


def add(findings: list[Finding], feature: str, severity: str, code: str, message: str, count: int = 1, sample: list[dict[str, Any]] | None = None) -> None:
    findings.append(Finding(feature=feature, severity=severity, code=code, message=message, count=count, sample=sample or []))


def add_static_presence(findings: list[Finding], root: Path, feature: str, rel: str, needles: list[str], ok_message: str, fail_message: str, code: str) -> None:
    text = read_text(root, rel)
    missing = [needle for needle in needles if needle not in text]
    if missing:
        add(findings, feature, MEDIUM, code, f"{fail_message} Fehlend: {', '.join(missing)}", len(missing), [{"file": rel, "missing": needle} for needle in missing])
    else:
        add(findings, feature, OK, code, ok_message)


def format_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    out = []
    for row in rows:
        out.append("  " + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


# ---------- DB-Audits ----------


def audit_core_db(db: SafeSqlite, findings: list[Finding]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    integrity = db.scalar("PRAGMA integrity_check", default="unknown")
    meta["integrity_check"] = integrity
    if integrity == "ok":
        add(findings, "Core", OK, "SQLITE_INTEGRITY_OK", "SQLite integrity_check ist ok.")
    else:
        add(findings, "Core", CRITICAL, "SQLITE_INTEGRITY_FAILED", f"SQLite integrity_check meldet: {integrity}")

    counts: dict[str, int] = {}
    for table in CORE_TABLES:
        if db.table_exists(table):
            if "is_deleted" in db.columns(table):
                counts[table] = db.count(table, active_clause())
            else:
                counts[table] = db.count(table)
            add(findings, "Core", OK, f"TABLE_{table.upper()}_PRESENT", f"Tabelle vorhanden: {table} ({counts[table]} aktive/gesamte Einträge je nach Soft-Delete).")
        else:
            counts[table] = 0
            add(findings, "Core", HIGH, f"TABLE_{table.upper()}_MISSING", f"Tabelle fehlt: {table}")
    meta["counts"] = counts

    if db.has_columns("audio_assets", "id", "source_url", "status", "song_id", "task_local_id", "suno_task_id", "audio_id", "project_id", "display_title", "metadata_json"):
        add(findings, "Core", OK, "AUDIO_ASSET_CORE_COLUMNS_OK", "audio_assets enthält die benötigten Kernspalten für den lokalen Master-Workflow.")
    else:
        missing = sorted(set(["id", "source_url", "status", "song_id", "task_local_id", "suno_task_id", "audio_id", "project_id", "display_title", "metadata_json"]) - db.columns("audio_assets"))
        add(findings, "Core", CRITICAL, "AUDIO_ASSET_CORE_COLUMNS_MISSING", "audio_assets fehlen Kernspalten.", len(missing), [{"missing": item} for item in missing])

    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "source_url", "is_deleted"):
        missing_source = db.count("audio_assets", f"{active_clause()} AND (source_url IS NULL OR TRIM(source_url) = '')")
        if missing_source:
            add(findings, "Core", CRITICAL, "ACTIVE_ASSET_WITHOUT_SOURCE_URL", "Aktive AudioAssets ohne source_url gefunden.", missing_source)
        else:
            add(findings, "Core", OK, "ACTIVE_ASSET_SOURCE_URL_OK", "Keine aktiven AudioAssets ohne source_url.")

    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "source_url", "is_deleted"):
        duplicates = db.rows(
            f"""
            SELECT source_url, COUNT(*) AS cnt, GROUP_CONCAT(id) AS ids
            FROM audio_assets
            WHERE {active_clause()} AND source_url IS NOT NULL AND TRIM(source_url) != ''
            GROUP BY source_url
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 20
            """
        )
        if duplicates:
            add(findings, "Core", HIGH, "DUPLICATE_ACTIVE_SOURCE_URL", "Aktive AudioAssets mit gleicher source_url gefunden.", len(duplicates), duplicates)
        else:
            add(findings, "Core", OK, "NO_DUPLICATE_ACTIVE_SOURCE_URL", "Keine aktiven doppelten source_url-Gruppen.")

    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "status", "is_deleted"):
        bad_status = db.rows(
            f"""
            SELECT status, COUNT(*) AS cnt
            FROM audio_assets
            WHERE {active_clause()} AND LOWER(COALESCE(status, '')) NOT IN ({','.join('?' for _ in VALID_ASSET_STATUSES)})
            GROUP BY status
            ORDER BY cnt DESC
            """,
            tuple(VALID_ASSET_STATUSES),
        )
        if bad_status:
            add(findings, "Core", MEDIUM, "UNEXPECTED_AUDIO_ASSET_STATUS", "Unerwartete AudioAsset-Statuswerte gefunden.", len(bad_status), bad_status)
        else:
            add(findings, "Core", OK, "AUDIO_ASSET_STATUS_VALUES_OK", "AudioAsset-Statuswerte sind plausibel.")

    return meta


def audit_srt(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "SRT"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/audio_assets.py",
        [
            '@router.post("/{audio_asset_id}/srt/generate")',
            '@router.get("/{audio_asset_id}/srt")',
            '@router.put("/{audio_asset_id}/srt")',
            '@router.get("/{audio_asset_id}/srt/download")',
        ],
        "SRT-Hauptrouten laufen über audio_asset_id.",
        "SRT-Hauptrouten über audio_asset_id sind nicht vollständig vorhanden.",
        "SRT_ASSET_ROUTES",
    )
    if file_exists(root, "app/routers/songs_srt.py"):
        add(findings, feature, LOW, "LEGACY_SONG_SRT_ROUTE_PRESENT", "Legacy-Route app/routers/songs_srt.py existiert noch. Das ist als Kompatibilität ok, bleibt aber bei mehreren Varianten potenziell uneindeutig.", 1, [{"file": "app/routers/songs_srt.py"}])

    if db.table_exists("audio_transcripts") and db.table_exists("audio_assets") and db.has_columns("audio_transcripts", "audio_asset_id"):
        active_orphan = db.rows(
            f"""
            SELECT t.id, t.audio_asset_id, t.status, t.backend, t.generated_at
            FROM audio_transcripts t
            LEFT JOIN audio_assets a ON a.id = t.audio_asset_id AND {active_clause('a')}
            WHERE a.id IS NULL
              AND LOWER(COALESCE(t.status, '')) NOT IN ({','.join('?' for _ in ARCHIVED_TRANSCRIPT_STATUSES)})
            ORDER BY t.id DESC
            LIMIT 20
            """,
            tuple(ARCHIVED_TRANSCRIPT_STATUSES),
        )
        archived_orphan_count = db.scalar(
            f"""
            SELECT COUNT(*)
            FROM audio_transcripts t
            LEFT JOIN audio_assets a ON a.id = t.audio_asset_id AND {active_clause('a')}
            WHERE a.id IS NULL
              AND LOWER(COALESCE(t.status, '')) IN ({','.join('?' for _ in ARCHIVED_TRANSCRIPT_STATUSES)})
            """,
            tuple(ARCHIVED_TRANSCRIPT_STATUSES),
            0,
        )
        if active_orphan:
            add(findings, feature, HIGH, "SRT_ORPHAN_TRANSCRIPTS", "Aktive AudioTranscript-Einträge zeigen auf fehlende oder gelöschte AudioAssets.", len(active_orphan), active_orphan)
        else:
            add(findings, feature, OK, "SRT_TRANSCRIPTS_LINKED_TO_ASSETS", "Alle aktiven AudioTranscript-Einträge zeigen auf aktive AudioAssets oder sind bewusst archiviert.")
        if archived_orphan_count:
            add(findings, feature, INFO, "SRT_ARCHIVED_ORPHAN_TRANSCRIPTS", "Archivierte Orphan-Transcripts vorhanden. Das ist für gelöschte Alt-Assets ok und wird nicht als aktiver Workflow-Fehler gewertet.", int(archived_orphan_count))

        duplicates = db.rows(
            """
            SELECT audio_asset_id, COUNT(*) AS cnt, GROUP_CONCAT(status) AS statuses, MAX(generated_at) AS latest_generated_at
            FROM audio_transcripts
            GROUP BY audio_asset_id
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 20
            """
        )
        if duplicates:
            add(findings, feature, INFO, "SRT_MULTIPLE_TRANSCRIPTS_PER_ASSET", "Mehrere Transcripts pro AudioAsset vorhanden. Das kann ok sein, sollte im UI bewusst als Versionierung/Latest-Auswahl behandelt werden.", len(duplicates), duplicates)
        else:
            add(findings, feature, OK, "SRT_ONE_OR_ZERO_TRANSCRIPTS_PER_ASSET", "Keine mehrfachen Transcript-Gruppen pro AudioAsset gefunden.")

    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "song_id", "is_deleted"):
        ambiguous = db.rows(
            f"""
            SELECT song_id, COUNT(*) AS asset_count, GROUP_CONCAT(id) AS asset_ids
            FROM audio_assets
            WHERE {active_clause()} AND song_id IS NOT NULL
            GROUP BY song_id
            HAVING COUNT(*) > 1
            ORDER BY asset_count DESC
            LIMIT 20
            """
        )
        if ambiguous:
            srt_asset_routes_present = all(needle in read_text(root, "app/routers/audio_assets.py") for needle in [
                '@router.post("/{audio_asset_id}/srt/generate")',
                '@router.get("/{audio_asset_id}/srt")',
                '@router.put("/{audio_asset_id}/srt")',
            ])
            severity = INFO if srt_asset_routes_present else MEDIUM
            add(findings, feature, severity, "SRT_SONG_ID_AMBIGUOUS_FOR_VARIANTS", "Songs mit mehreren AudioAsset-Varianten gefunden. Das ist fachlich normal; kritisch wäre es nur, wenn SRT noch song_id-only arbeitet.", len(ambiguous), ambiguous)
        else:
            add(findings, feature, OK, "SRT_NO_MULTIVARIANT_SONG_AMBIGUITY", "Keine Mehrvarianten-Songs gefunden, die song_id-SRT-Aufrufe uneindeutig machen würden.")


def audit_stems(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Stems"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/audio_assets.py",
        [
            '@router.post("/{audio_asset_id}/stems/generate")',
            '@router.get("/{audio_asset_id}/stems")',
            '@router.get("/{audio_asset_id}/stems/download")',
            '@router.get("/{audio_asset_id}/stems/{kind}/download")',
            '@router.get("/{audio_asset_id}/stems/{kind}/stream")',
        ],
        "Stem-Hauptrouten laufen über audio_asset_id.",
        "Stem-Hauptrouten über audio_asset_id sind nicht vollständig vorhanden.",
        "STEMS_ASSET_ROUTES",
    )
    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "metadata_json", "is_deleted"):
        stem_rows = []
        for row in db.rows(f"SELECT id, display_title, metadata_json FROM audio_assets WHERE {active_clause()} AND metadata_json IS NOT NULL ORDER BY id DESC"):
            metadata = parse_json(row.get("metadata_json"))
            if isinstance(metadata, dict) and isinstance(metadata.get("stems"), dict):
                stems = metadata.get("stems") or {}
                stem_rows.append({"audio_asset_id": row["id"], "title": row.get("display_title"), "status": stems.get("status"), "has_files": bool(stems.get("files"))})
        if stem_rows:
            missing_files = [item for item in stem_rows if str(item.get("status") or "").lower() in {"completed", "success", "done"} and not item.get("has_files")]
            if missing_files:
                add(findings, feature, MEDIUM, "STEMS_COMPLETED_WITHOUT_FILES_METADATA", "Stem-Metadaten melden abgeschlossen, enthalten aber keine files-Struktur.", len(missing_files), missing_files[:20])
            else:
                add(findings, feature, OK, "STEMS_METADATA_PLAUSIBLE", f"Stem-Metadaten bei {len(stem_rows)} AudioAssets wirken plausibel.")
        else:
            add(findings, feature, INFO, "STEMS_NO_EXISTING_METADATA", "Keine vorhandenen Stem-Metadaten gefunden. Das ist ok, wenn noch keine Stems erzeugt wurden.")


def audit_wav(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "WAV"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/audio_assets.py",
        [
            '@router.post("/{audio_asset_id}/wav/convert")',
            '@router.get("/{audio_asset_id}/wav/download")',
            "convert_asset_to_wav(db: Session, audio_asset_id: int",
        ],
        "WAV-Konvertierung und Download laufen über audio_asset_id.",
        "WAV-Konvertierung/Download über audio_asset_id ist nicht vollständig vorhanden.",
        "WAV_ASSET_ROUTES",
    )
    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "metadata_json", "is_deleted"):
        wav_rows = []
        for row in db.rows(f"SELECT id, display_title, local_path, public_url, metadata_json FROM audio_assets WHERE {active_clause()} AND metadata_json IS NOT NULL ORDER BY id DESC"):
            metadata = parse_json(row.get("metadata_json"))
            if isinstance(metadata, dict) and isinstance(metadata.get("wav_conversion"), dict):
                wav = metadata.get("wav_conversion") or {}
                wav_rows.append({"audio_asset_id": row["id"], "title": row.get("display_title"), "public_url": wav.get("public_url"), "local_path": wav.get("local_path"), "filename": wav.get("filename")})
        missing_target = [item for item in wav_rows if not (item.get("public_url") or item.get("local_path") or item.get("filename"))]
        if missing_target:
            add(findings, feature, MEDIUM, "WAV_METADATA_WITHOUT_TARGET", "WAV-Metadaten ohne public_url/local_path/filename gefunden.", len(missing_target), missing_target[:20])
        elif wav_rows:
            add(findings, feature, OK, "WAV_METADATA_PLAUSIBLE", f"WAV-Metadaten bei {len(wav_rows)} AudioAssets wirken plausibel.")
        else:
            add(findings, feature, INFO, "WAV_NO_EXISTING_METADATA", "Keine vorhandenen WAV-Metadaten gefunden. Das ist ok, wenn noch keine WAV-Konvertierung genutzt wurde.")


def audit_player(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Player"
    add_static_presence(
        findings,
        root,
        feature,
        "frontend-react/src/components/MiniPlayer.jsx",
        ["queue", "currentIndex", "onOpenDetails", "onFavoriteChange", "audioRef"],
        "React-MiniPlayer ist vorhanden und nutzt Asset-Queue/Details/Favoriten-Hooks.",
        "React-MiniPlayer wirkt unvollständig oder fehlt.",
        "PLAYER_MINIPLAYER_REACT",
    )
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/archive.py",
        [
            '@router.get("/audio/{asset_id}/stream")',
            '@router.get("/audio/{asset_id}/download")',
            '@router.get("/audio/{asset_id}/waveform"',
        ],
        "Player-nahe Backend-Routen laufen über asset_id.",
        "Player-nahe Backend-Routen über asset_id fehlen teilweise.",
        "PLAYER_ARCHIVE_ROUTES",
    )
    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "source_url", "public_url", "status", "is_deleted"):
        unplayable = db.rows(
            f"""
            SELECT id, display_title, status, source_url, public_url, local_path
            FROM audio_assets
            WHERE {active_clause()} AND (source_url IS NULL OR TRIM(source_url) = '') AND (public_url IS NULL OR TRIM(public_url) = '')
            ORDER BY id DESC
            LIMIT 20
            """
        )
        if unplayable:
            add(findings, feature, CRITICAL, "PLAYER_ASSET_WITHOUT_PLAYABLE_URL", "Aktive AudioAssets ohne source_url und ohne public_url gefunden.", len(unplayable), unplayable)
        else:
            add(findings, feature, OK, "PLAYER_ASSETS_HAVE_URLS", "Aktive AudioAssets besitzen mindestens source_url oder public_url.")


def audit_download(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Download"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/archive.py",
        ['@router.get("/audio/{asset_id}/download")'],
        "Library-Audio-Download läuft über asset_id.",
        "Library-Audio-Download über asset_id fehlt.",
        "DOWNLOAD_ARCHIVE_ROUTE",
    )
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/audio_assets.py",
        [
            '@router.get("/{audio_asset_id}/bundle/download")',
            '@router.get("/bulk/bundle/download")',
            '@router.get("/{audio_asset_id}/srt/download")',
            '@router.get("/{audio_asset_id}/wav/download")',
            '@router.get("/{audio_asset_id}/stems/download")',
        ],
        "Bundle/SRT/WAV/Stem-Downloads laufen über audio_asset_id.",
        "Nicht alle Download-Routen laufen sauber über audio_asset_id.",
        "DOWNLOAD_ASSET_ROUTES",
    )
    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "filename", "display_title", "is_deleted"):
        missing_names = db.rows(
            f"""
            SELECT id, display_title, title, filename
            FROM audio_assets
            WHERE {active_clause()} AND (COALESCE(display_title, title, filename, '') = '')
            ORDER BY id DESC
            LIMIT 20
            """
        )
        if missing_names:
            add(findings, feature, LOW, "DOWNLOAD_ASSET_WITHOUT_DISPLAY_NAME", "AudioAssets ohne nutzbaren Download-/Anzeigenamen gefunden.", len(missing_names), missing_names)
        else:
            add(findings, feature, OK, "DOWNLOAD_NAMES_AVAILABLE", "AudioAssets besitzen nutzbare Titel/Filenames für Downloads.")


def audit_favorites(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Favoriten"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/audio_assets.py",
        [
            '@router.get("/favorites"',
            '@router.patch("/{audio_asset_id}/favorite")',
            "_sync_parent_favorite_state",
        ],
        "Favoriten laufen primär über AudioAsset und synchronisieren Song/Projekt.",
        "Favoritenroute/Synchronisierung über AudioAsset fehlt teilweise.",
        "FAVORITES_ASSET_ROUTES",
    )
    if db.table_exists("audio_assets") and db.table_exists("songs") and db.has_columns("audio_assets", "song_id", "is_favorite", "is_deleted") and db.has_columns("songs", "is_favorite", "is_deleted"):
        mismatch_song = db.rows(
            f"""
            SELECT s.id AS song_id, s.title, s.is_favorite AS song_is_favorite,
                   MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END) AS any_asset_favorite,
                   GROUP_CONCAT(CASE WHEN a.is_favorite THEN a.id END) AS favorite_asset_ids
            FROM songs s
            LEFT JOIN audio_assets a ON a.song_id = s.id AND {active_clause('a')}
            WHERE {active_clause('s')}
            GROUP BY s.id
            HAVING COALESCE(s.is_favorite, 0) != COALESCE(any_asset_favorite, 0)
            LIMIT 20
            """
        )
        if mismatch_song:
            add(findings, feature, MEDIUM, "FAVORITE_SONG_SYNC_MISMATCH", "Song-Favoritstatus passt nicht zu zugehörigen AudioAsset-Favoriten.", len(mismatch_song), mismatch_song)
        else:
            add(findings, feature, OK, "FAVORITE_SONG_SYNC_OK", "Song-Favoritstatus ist mit AudioAsset-Favoriten synchron.")

    if db.table_exists("audio_assets") and db.table_exists("audio_projects") and db.has_columns("audio_assets", "project_id", "is_favorite", "is_deleted") and db.has_columns("audio_projects", "is_favorite", "is_deleted"):
        mismatch_project = db.rows(
            f"""
            SELECT p.id AS project_id, p.title, p.is_favorite AS project_is_favorite,
                   MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END) AS any_asset_favorite,
                   GROUP_CONCAT(CASE WHEN a.is_favorite THEN a.id END) AS favorite_asset_ids
            FROM audio_projects p
            LEFT JOIN audio_assets a ON a.project_id = p.id AND {active_clause('a')}
            WHERE {active_clause('p')}
            GROUP BY p.id
            HAVING COALESCE(p.is_favorite, 0) != COALESCE(any_asset_favorite, 0)
            LIMIT 20
            """
        )
        if mismatch_project:
            add(findings, feature, MEDIUM, "FAVORITE_PROJECT_SYNC_MISMATCH", "Projekt-Favoritstatus passt nicht zu zugehörigen AudioAsset-Favoriten.", len(mismatch_project), mismatch_project)
        else:
            add(findings, feature, OK, "FAVORITE_PROJECT_SYNC_OK", "Projekt-Favoritstatus ist mit AudioAsset-Favoriten synchron.")


def audit_cover(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Cover"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/archive.py",
        [
            '@router.post("/audio/{asset_id}/create-cover-image"',
            '@router.post("/audio/{asset_id}/generate-ai-cover"',
        ],
        "Cover-Erzeugung läuft über asset_id.",
        "Cover-Erzeugung über asset_id fehlt teilweise.",
        "COVER_ASSET_ROUTES",
    )
    add_static_presence(
        findings,
        root,
        feature,
        "app/services/replicate_cover_service.py",
        ["audio_asset_id", "AudioAsset", "image_url"],
        "Replicate-Cover-Service arbeitet mit AudioAsset-Bezug.",
        "Replicate-Cover-Service nutzt AudioAsset-Bezug nicht eindeutig.",
        "COVER_REPLICATE_ASSET_BINDING",
    )
    if db.table_exists("audio_assets") and db.has_columns("audio_assets", "image_url", "metadata_json", "is_deleted"):
        generated_without_asset_image = []
        for row in db.rows(f"SELECT id, display_title, image_url, metadata_json FROM audio_assets WHERE {active_clause()} AND metadata_json IS NOT NULL ORDER BY id DESC"):
            metadata = parse_json(row.get("metadata_json"))
            if not isinstance(metadata, dict):
                continue
            generated_cover = metadata.get("generated_cover") or metadata.get("cover_cache")
            if isinstance(generated_cover, dict) and (generated_cover.get("public_url") or generated_cover.get("url")) and not row.get("image_url"):
                generated_without_asset_image.append({"audio_asset_id": row["id"], "title": row.get("display_title"), "cover_meta": generated_cover})
        if generated_without_asset_image:
            add(findings, feature, MEDIUM, "COVER_METADATA_WITHOUT_ASSET_IMAGE", "Cover-Metadaten vorhanden, aber audio_assets.image_url ist leer.", len(generated_without_asset_image), generated_without_asset_image[:20])
        else:
            add(findings, feature, OK, "COVER_ASSET_IMAGE_CONSISTENT", "Keine offensichtlichen Cover-Metadaten ohne AudioAsset-image_url gefunden.")


def audit_songdetails(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Songdetails"
    add_static_presence(
        findings,
        root,
        feature,
        "frontend-react/src/pages/LibraryPage.jsx",
        ["openAsset", "audio_asset", "selectedProject", "song_id", "audio_assets"],
        "Library/Songdetails enthalten Asset- und Projektbezug.",
        "Library/Songdetails wirken nicht ausreichend asset-zentriert.",
        "SONGDETAILS_FRONTEND_ASSET_CONTEXT",
    )
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/archive.py",
        ['@router.get("/audio/{asset_id}"'],
        "Detail-API für einzelne AudioAssets ist vorhanden.",
        "Detail-API für einzelne AudioAssets fehlt.",
        "SONGDETAILS_ASSET_DETAIL_ROUTE",
    )
    if db.table_exists("audio_assets") and db.table_exists("songs") and db.has_columns("audio_assets", "song_id", "display_title", "is_deleted"):
        assets_without_song = db.rows(
            f"""
            SELECT a.id AS audio_asset_id, a.display_title, a.song_id, a.project_id, a.status
            FROM audio_assets a
            LEFT JOIN songs s ON s.id = a.song_id AND {active_clause('s')}
            WHERE {active_clause('a')} AND a.song_id IS NOT NULL AND s.id IS NULL
            ORDER BY a.id DESC
            LIMIT 20
            """
        )
        if assets_without_song:
            add(findings, feature, HIGH, "SONGDETAILS_ASSET_POINTS_TO_MISSING_SONG", "AudioAssets zeigen auf fehlende/gelöschte Songs.", len(assets_without_song), assets_without_song)
        else:
            add(findings, feature, OK, "SONGDETAILS_ASSET_SONG_LINKS_OK", "AudioAsset→Song-Verweise sind plausibel.")


def audit_production(db: SafeSqlite, root: Path, findings: list[Finding]) -> None:
    feature = "Production"
    add_static_presence(
        findings,
        root,
        feature,
        "app/routers/production.py",
        [
            '@router.get("/audio/{asset_id}/workflow")',
            '@router.patch("/audio/{asset_id}/workflow")',
            '@router.post("/audio/{asset_id}/duplicate-version")',
            '@router.get("/audio/{asset_id}/youtube-package")',
            '@router.get("/audio/{asset_id}/video-plan")',
            '@router.post("/audio/{asset_id}/favorite")',
            '@router.post("/audio/{asset_id}/final")',
        ],
        "Production-Routen sind überwiegend asset-zentriert.",
        "Production-Routen sind nicht vollständig asset-zentriert.",
        "PRODUCTION_ASSET_ROUTES",
    )
    if db.table_exists("audio_projects") and db.table_exists("audio_assets") and db.has_columns("audio_projects", "final_audio_asset_id", "is_deleted"):
        bad_final = db.rows(
            f"""
            SELECT p.id AS project_id, p.title, p.final_audio_asset_id
            FROM audio_projects p
            LEFT JOIN audio_assets a ON a.id = p.final_audio_asset_id AND {active_clause('a')}
            WHERE {active_clause('p')} AND p.final_audio_asset_id IS NOT NULL AND a.id IS NULL
            ORDER BY p.id DESC
            LIMIT 20
            """
        )
        if bad_final:
            add(findings, feature, HIGH, "PRODUCTION_FINAL_ASSET_MISSING", "AudioProjects zeigen auf fehlende/gelöschte final_audio_asset_id.", len(bad_final), bad_final)
        else:
            add(findings, feature, OK, "PRODUCTION_FINAL_ASSET_LINKS_OK", "final_audio_asset_id-Verweise sind plausibel.")

    if db.table_exists("audio_assets") and db.table_exists("audio_projects") and db.has_columns("audio_assets", "project_id", "is_deleted"):
        orphan_project_assets = db.rows(
            f"""
            SELECT a.id AS audio_asset_id, a.display_title, a.project_id
            FROM audio_assets a
            LEFT JOIN audio_projects p ON p.id = a.project_id AND {active_clause('p')}
            WHERE {active_clause('a')} AND a.project_id IS NOT NULL AND p.id IS NULL
            ORDER BY a.id DESC
            LIMIT 20
            """
        )
        if orphan_project_assets:
            add(findings, feature, HIGH, "PRODUCTION_ASSET_PROJECT_MISSING", "AudioAssets zeigen auf fehlende/gelöschte Projekte.", len(orphan_project_assets), orphan_project_assets)
        else:
            add(findings, feature, OK, "PRODUCTION_ASSET_PROJECT_LINKS_OK", "AudioAsset→Projekt-Verweise sind plausibel.")


def audit_notifications(db: SafeSqlite, findings: list[Finding]) -> None:
    feature = "Status/Notifications"
    if not db.table_exists("status_notifications") or not db.has_columns("status_notifications", "target_payload", "target_tab", "status", "is_deleted"):
        add(findings, feature, INFO, "NOTIFICATIONS_TABLE_NOT_CHECKED", "StatusNotification-Tabelle oder Zielspalten fehlen; Notification-Zielprüfung übersprungen.")
        return

    rows = db.rows(
        f"""
        SELECT id, event_type, title, target_tab, target_payload, task_local_id, content_type, content_id, created_at
        FROM status_notifications
        WHERE {active_clause()} AND target_payload IS NOT NULL
        ORDER BY id DESC
        LIMIT 500
        """
    )
    success_like = []
    missing_asset_target = []
    for row in rows:
        event = str(row.get("event_type") or "").lower()
        title = str(row.get("title") or "").lower()
        payload = parse_json(row.get("target_payload"))
        if not isinstance(payload, dict):
            continue
        is_success = any(token in event for token in ("completed", "success", "generated", "import_completed")) or any(token in title for token in ("abgeschlossen", "erfolgreich", "success"))
        if not is_success:
            continue
        success_like.append(row)
        has_asset = bool(payload.get("audio_asset_id") or payload.get("primary_audio_asset_id") or payload.get("audio_asset_ids"))
        task_type = str(payload.get("task_type") or row.get("event_type") or "").lower()
        audio_related = any(token in task_type for token in ("music", "audio", "srt", "stem", "wav", "cover", "import", "opencli", "suno"))
        is_batch_summary = task_type.startswith("bulk_") or str(row.get("event_type") or "").lower().startswith("bulk_")
        if audio_related and not has_asset and row.get("target_tab") not in {"status", None, ""}:
            missing_asset_target.append({
                "id": row.get("id"),
                "event_type": row.get("event_type"),
                "title": row.get("title"),
                "target_tab": row.get("target_tab"),
                "target_payload": payload,
                "expected_target": "status" if is_batch_summary else "audio_asset_id/primary_audio_asset_id/audio_asset_ids",
            })
    if missing_asset_target:
        add(findings, feature, MEDIUM, "SUCCESS_NOTIFICATION_WITHOUT_ASSET_TARGET", "Erfolgsnahe Audio-Notifications ohne AudioAsset-Ziel gefunden.", len(missing_asset_target), missing_asset_target[:20])
    else:
        add(findings, feature, OK, "SUCCESS_NOTIFICATIONS_ASSET_TARGET_OK", f"Keine problematischen Erfolgs-Notifications ohne Asset-Ziel gefunden ({len(success_like)} success-nahe Notifications geprüft).")


# ---------- Report ----------


def summarize(findings: list[Finding]) -> dict[str, Any]:
    by_severity: dict[str, int] = {sev: 0 for sev in [OK, INFO, LOW, MEDIUM, HIGH, CRITICAL]}
    by_feature: dict[str, dict[str, int]] = {}
    for item in findings:
        by_severity[item.severity] = by_severity.get(item.severity, 0) + item.count
        by_feature.setdefault(item.feature, {})[item.severity] = by_feature.setdefault(item.feature, {}).get(item.severity, 0) + item.count
    max_sev = OK
    for item in findings:
        if SEVERITY_RANK[item.severity] > SEVERITY_RANK[max_sev]:
            max_sev = item.severity
    return {"by_severity": by_severity, "by_feature": by_feature, "max_severity": max_sev}


def render_markdown(meta: dict[str, Any], findings: list[Finding]) -> str:
    summary = summarize(findings)
    lines: list[str] = []
    lines.append("# Feature Root Workflow Audit")
    lines.append("")
    lines.append(f"Erstellt: `{meta['created_at']}`")
    lines.append(f"Projektpfad: `{meta['project_root']}`")
    lines.append(f"Datenbank: `{meta['database']}`")
    lines.append(f"SQLite integrity_check: `{meta.get('integrity_check', 'unknown')}`")
    lines.append(f"Maximale Schwere: `{summary['max_severity']}`")
    lines.append("")
    lines.append("## Zielregel")
    lines.append("")
    lines.append("```text")
    lines.append("audio_assets = zentrale Wahrheit für alles Abspielbare")
    lines.append("suno_tasks   = Prozess-/Statuslog")
    lines.append("songs        = Metadaten/Lyrics/Prompt")
    lines.append("Alle konkreten Audio-Funktionen sollen über audio_asset_id laufen.")
    lines.append("```")
    lines.append("")

    counts = meta.get("counts") or {}
    if counts:
        lines.append("## Bestandszahlen")
        lines.append("")
        lines.append("| Tabelle | Anzahl |")
        lines.append("| --- | ---: |")
        for table, count in counts.items():
            lines.append(f"| {table} | {count} |")
        lines.append("")

    lines.append("## Zusammenfassung nach Schwere")
    lines.append("")
    lines.append("| Schwere | Anzahl |")
    lines.append("| --- | ---: |")
    for severity in [CRITICAL, HIGH, MEDIUM, LOW, INFO, OK]:
        lines.append(f"| {severity} | {summary['by_severity'].get(severity, 0)} |")
    lines.append("")

    lines.append("## Zusammenfassung nach Funktion")
    lines.append("")
    lines.append("| Funktion | CRITICAL | HIGH | MEDIUM | LOW | INFO | OK |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for feature in ["Core"] + FEATURE_ORDER + ["Status/Notifications"]:
        stats = summary["by_feature"].get(feature, {})
        lines.append(f"| {feature} | {stats.get(CRITICAL, 0)} | {stats.get(HIGH, 0)} | {stats.get(MEDIUM, 0)} | {stats.get(LOW, 0)} | {stats.get(INFO, 0)} | {stats.get(OK, 0)} |")
    lines.append("")

    relevant = [item for item in findings if item.severity != OK]
    if relevant:
        lines.append("## Befunde")
        lines.append("")
        lines.append("| Funktion | Schwere | Code | Anzahl | Beschreibung |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for item in sorted(relevant, key=lambda x: (-SEVERITY_RANK[x.severity], x.feature, x.code)):
            msg = item.message.replace("|", "\\|")
            lines.append(f"| {item.feature} | {item.severity} | {item.code} | {item.count} | {msg} |")
        lines.append("")
        for item in sorted(relevant, key=lambda x: (-SEVERITY_RANK[x.severity], x.feature, x.code)):
            if item.sample:
                lines.append(f"### Beispiele: {item.feature} / {item.code}")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(item.sample[:10], ensure_ascii=False, indent=2, default=str))
                lines.append("```")
                lines.append("")
    else:
        lines.append("## Befunde")
        lines.append("")
        lines.append("Keine relevanten Befunde oberhalb OK.")
        lines.append("")

    lines.append("## Geprüfte Funktionen")
    lines.append("")
    for feature in FEATURE_ORDER:
        lines.append(f"- {feature}")
    lines.append("")
    lines.append("## Hinweis")
    lines.append("")
    lines.append("Dieses Skript führt keine SRT-, Stem-, WAV-, Cover- oder Task-Aktionen aus. Es liest nur Datenbank, Codepfade und vorhandene Metadaten.")
    lines.append("")
    return "\n".join(lines)


def print_console(meta: dict[str, Any], findings: list[Finding]) -> None:
    summary = summarize(findings)
    print("Feature Root Workflow Audit")
    print(f"Projektpfad : {meta['project_root']}")
    print(f"Datenbank   : {meta['database']}")
    print(f"Integrity   : {meta.get('integrity_check', 'unknown')}")
    print(f"Max Severity: {summary['max_severity']}")
    print()
    counts = meta.get("counts") or {}
    if counts:
        print("Bestandszahlen:")
        rows = [["Tabelle", "Anzahl"]] + [[table, str(count)] for table, count in counts.items()]
        print(format_table(rows))
        print()
    print("Schweregrade:")
    rows = [["Schwere", "Anzahl"]] + [[sev, str(summary["by_severity"].get(sev, 0))] for sev in [CRITICAL, HIGH, MEDIUM, LOW, INFO, OK]]
    print(format_table(rows))
    print()
    relevant = [item for item in findings if item.severity != OK]
    if relevant:
        print("Befunde:")
        for item in sorted(relevant, key=lambda x: (-SEVERITY_RANK[x.severity], x.feature, x.code)):
            print(f"  [{item.severity:<8}] {item.feature:<22} {item.code}: {item.count} - {item.message}")
            for sample in item.sample[:3]:
                print(f"    Beispiel: {sample}")
    else:
        print("Befunde: keine relevanten Befunde oberhalb OK.")


def write_report(root: Path, markdown: str, explicit_path: str | None = None) -> Path:
    if explicit_path:
        target = Path(explicit_path).expanduser()
        if not target.is_absolute():
            target = root / target
    else:
        report_dir = root / "storage" / "reports"
        target = report_dir / f"feature_root_workflow_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


# ---------- Hauptprogramm ----------


def run(root: Path, db_path: Path) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []
    meta: dict[str, Any] = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(root),
        "database": str(db_path),
    }

    if not db_path.exists():
        add(findings, "Core", CRITICAL, "DATABASE_NOT_FOUND", f"Datenbank nicht gefunden: {db_path}")
        meta["integrity_check"] = "missing"
    else:
        try:
            with SafeSqlite(db_path) as db:
                meta.update(audit_core_db(db, findings))
                audit_srt(db, root, findings)
                audit_stems(db, root, findings)
                audit_wav(db, root, findings)
                audit_player(db, root, findings)
                audit_download(db, root, findings)
                audit_favorites(db, root, findings)
                audit_cover(db, root, findings)
                audit_songdetails(db, root, findings)
                audit_production(db, root, findings)
                audit_notifications(db, findings)
        except sqlite3.Error as exc:
            add(findings, "Core", CRITICAL, "DATABASE_READ_FAILED", f"Datenbank konnte nicht read-only geöffnet/geprüft werden: {exc}")
            meta["integrity_check"] = "read_failed"

    # Statische Prüfungen laufen auch ohne DB weiter.
    for rel in [
        "app/routers/audio_assets.py",
        "app/routers/archive.py",
        "app/routers/production.py",
        "frontend-react/src/pages/LibraryPage.jsx",
        "frontend-react/src/components/MiniPlayer.jsx",
        "frontend-react/src/api/client.js",
    ]:
        if file_exists(root, rel):
            add(findings, "Core", OK, f"STATIC_FILE_PRESENT_{rel.upper().replace('/', '_').replace('.', '_')}", f"Datei vorhanden: {rel}")
        else:
            add(findings, "Core", HIGH, f"STATIC_FILE_MISSING_{rel.upper().replace('/', '_').replace('.', '_')}", f"Datei fehlt: {rel}")

    return meta, findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Audit für SRT/Stems/WAV/Player/Download/Favoriten/Cover/Songdetails/Production gegen den einheitlichen audio_assets-Workflow.")
    parser.add_argument("--database", "--db", dest="database", default=None, help="Pfad zur SQLite-Datenbank. Default: ./suno_fastapi_app.db oder DATABASE_URL.")
    parser.add_argument("--project-root", default=None, help="Projektwurzel. Default: automatisch anhand des Skriptpfads.")
    parser.add_argument("--write-report", action="store_true", help="Markdown-Report nach storage/reports schreiben.")
    parser.add_argument("--report", default=None, help="Expliziter Report-Pfad. Aktiviert automatisch --write-report.")
    parser.add_argument("--json", action="store_true", help="Zusätzlich maschinenlesbares JSON auf stdout ausgeben.")
    parser.add_argument("--fail-on", choices=[LOW, MEDIUM, HIGH, CRITICAL], default=None, help="Exitcode 2 ab dieser Schwere. Ohne Option immer Exitcode 0, solange das Skript selbst läuft.")
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve() if args.project_root else project_root().resolve()
    db_path = resolve_db_path(args.database, root)

    meta, findings = run(root, db_path)
    markdown = render_markdown(meta, findings)
    print_console(meta, findings)

    if args.write_report or args.report:
        target = write_report(root, markdown, args.report)
        print()
        print(f"Report geschrieben: {target}")

    if args.json:
        payload = {"meta": meta, "summary": summarize(findings), "findings": [item.as_dict() for item in findings]}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    if args.fail_on:
        threshold = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK[item.severity] >= threshold for item in findings):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
