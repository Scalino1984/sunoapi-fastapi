#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import Any

AUDIO_KEYS = {
    "audio_url", "audiourl", "source_audio_url", "sourceaudiourl",
    "stream_audio_url", "streamaudiourl", "download_url", "downloadurl",
    "mp3_url", "mp3url", "wav_url", "wavurl", "sourceaudiourl",
}
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}


@dataclass
class AuditFinding:
    code: str
    severity: str
    count: int
    message: str
    sample: list[dict[str, Any]]


def project_root() -> Path:
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "scripts" else Path.cwd()


def resolve_db_path(value: str | None) -> Path:
    if value:
        raw = value.strip()
    else:
        raw = os.environ.get("DATABASE_URL", "sqlite:///suno_fastapi_app.db")
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1)).expanduser().resolve()
    if raw.startswith("sqlite://"):
        return Path(raw.replace("sqlite://", "", 1)).expanduser().resolve()
    return Path(raw).expanduser().resolve()


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


def walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def normalize_key(key: str) -> str:
    return key.replace("-", "_").replace(" ", "_").lower()


def is_suno_share_page_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    host = (parsed.netloc or "").lower().split(":", 1)[0]
    path = (parsed.path or "").lower().rstrip("/")
    return host in {"suno.com", "www.suno.com"} and path.startswith("/song/")


def url_extension(value: str) -> str:
    return Path(unquote(urlparse(value).path)).suffix.lower()


def looks_like_audio_url(value: Any, *, key_hint: str | None = None) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    lowered = text.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    if is_suno_share_page_url(text):
        return False
    extension = url_extension(text)
    if extension in IMAGE_EXTENSIONS:
        return False
    if extension in AUDIO_EXTENSIONS:
        return True
    normalized_key = normalize_key(key_hint or "")
    if normalized_key in AUDIO_KEYS:
        return True
    # Fallback nur bei eindeutig technischen Audio-/Download-/Stream-Markern.
    # "song" und "music" sind bewusst ausgeschlossen, weil sie oft HTML-Seiten
    # oder Marketing-/Share-Links bezeichnen.
    return any(marker in lowered for marker in ("audio", "download", "stream", "mp3", "wav", "m4a", "flac", "aac", "ogg"))


def extract_audio_candidates(*payloads: Any) -> list[dict[str, Any]]:
    seen: set[tuple[str | None, str]] = set()
    result: list[dict[str, Any]] = []
    for payload in payloads:
        for item in walk_json(payload):
            if not isinstance(item, dict):
                continue
            source_url = None
            for key, value in item.items():
                if not isinstance(value, str):
                    continue
                norm = normalize_key(str(key))
                if norm in AUDIO_KEYS and looks_like_audio_url(value, key_hint=str(key)):
                    source_url = value
                    break
            if not source_url:
                for value in item.values():
                    if looks_like_audio_url(value):
                        source_url = value
                        break
            if not source_url:
                continue
            audio_id = None
            for key in ("audio_id", "audioId", "id"):
                if item.get(key):
                    audio_id = str(item.get(key))
                    break
            title = None
            for key in ("title", "name", "songTitle"):
                if item.get(key):
                    title = str(item.get(key))
                    break
            dedupe = (audio_id, source_url)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            result.append({"audio_id": audio_id, "source_url": source_url, "title": title})
    return result


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def count_rows(con: sqlite3.Connection, table: str, active_only: bool = False) -> int:
    if not table_exists(con, table):
        return 0
    columns = table_columns(con, table)
    where = " WHERE COALESCE(is_deleted, 0) = 0" if active_only and "is_deleted" in columns else ""
    return int(con.execute(f"SELECT COUNT(*) FROM {table}{where}").fetchone()[0])


def select_dicts(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    return [dict(row) for row in con.execute(sql, params).fetchall()]


def asset_match_exists(con: sqlite3.Connection, *, source_url: str | None, audio_id: str | None, task_id: int | None, suno_task_id: str | None) -> bool:
    if not table_exists(con, "audio_assets"):
        return False
    columns = table_columns(con, "audio_assets")
    conditions = []
    params: list[Any] = []
    if "is_deleted" in columns:
        conditions.append("COALESCE(is_deleted, 0) = 0")
    if source_url and "source_url" in columns:
        conditions.append("source_url = ?")
        params.append(source_url)
    if len(conditions) > (1 if "is_deleted" in columns else 0):
        if con.execute(f"SELECT 1 FROM audio_assets WHERE {' AND '.join(conditions)} LIMIT 1", tuple(params)).fetchone():
            return True
    base = ["COALESCE(is_deleted, 0) = 0"] if "is_deleted" in columns else []
    or_parts = []
    params = []
    if audio_id and "audio_id" in columns:
        or_parts.append("audio_id = ?")
        params.append(audio_id)
    if task_id is not None and "task_local_id" in columns:
        or_parts.append("task_local_id = ?")
        params.append(task_id)
    if suno_task_id and "suno_task_id" in columns:
        or_parts.append("suno_task_id = ?")
        params.append(suno_task_id)
    if not or_parts:
        return False
    where = " AND ".join(base + ["(" + " OR ".join(or_parts) + ")"])
    return con.execute(f"SELECT 1 FROM audio_assets WHERE {where} LIMIT 1", tuple(params)).fetchone() is not None


def build_audit(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {name: table_exists(con, name) for name in ("suno_tasks", "songs", "audio_assets", "audio_projects", "audio_transcripts", "status_notifications")}
        counts = {
            "suno_tasks": count_rows(con, "suno_tasks", active_only=True),
            "songs": count_rows(con, "songs", active_only=True),
            "audio_assets": count_rows(con, "audio_assets", active_only=True),
            "audio_projects": count_rows(con, "audio_projects", active_only=True),
            "audio_transcripts": count_rows(con, "audio_transcripts", active_only=False),
            "status_notifications": count_rows(con, "status_notifications", active_only=True),
        }
        findings: list[AuditFinding] = []

        if integrity.lower() != "ok":
            findings.append(AuditFinding("SQLITE_INTEGRITY", "critical", 1, "SQLite integrity_check ist nicht OK.", [{"result": integrity}]))

        missing_tables = [table for table, exists in tables.items() if not exists and table in {"suno_tasks", "songs", "audio_assets"}]
        if missing_tables:
            findings.append(AuditFinding("MISSING_CORE_TABLE", "critical", len(missing_tables), "Kern-Tabellen fehlen.", [{"table": t} for t in missing_tables]))

        # Erfolgreiche Tasks mit Audio-Kandidaten, aber ohne AudioAsset.
        missing_task_assets: list[dict[str, Any]] = []
        tasks_with_candidates = 0
        if table_exists(con, "suno_tasks"):
            columns = table_columns(con, "suno_tasks")
            where = []
            if "is_deleted" in columns:
                where.append("COALESCE(is_deleted, 0) = 0")
            if "status" in columns:
                placeholders = ",".join("?" for _ in SUCCESS_STATUSES)
                where.append(f"UPPER(COALESCE(status, '')) IN ({placeholders})")
                params = tuple(sorted(SUCCESS_STATUSES))
            else:
                params = ()
            sql = "SELECT id, task_id, task_type, status, response_payload, result_payload FROM suno_tasks"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY id ASC"
            for row in con.execute(sql, params).fetchall():
                response_payload = parse_json(row["response_payload"])
                result_payload = parse_json(row["result_payload"])
                candidates = extract_audio_candidates(response_payload, result_payload)
                if not candidates:
                    continue
                tasks_with_candidates += 1
                for candidate in candidates:
                    if not asset_match_exists(con, source_url=candidate.get("source_url"), audio_id=candidate.get("audio_id"), task_id=row["id"], suno_task_id=row["task_id"]):
                        missing_task_assets.append({
                            "task_local_id": row["id"],
                            "suno_task_id": row["task_id"],
                            "task_type": row["task_type"],
                            "status": row["status"],
                            "audio_id": candidate.get("audio_id"),
                            "source_url": candidate.get("source_url"),
                            "title": candidate.get("title"),
                        })
                        break
        if missing_task_assets:
            findings.append(AuditFinding("TASK_AUDIO_WITHOUT_ASSET", "high", len(missing_task_assets), "Erfolgreiche Tasks liefern Audio-URLs, haben aber keinen aktiven AudioAsset-Eintrag.", missing_task_assets[:20]))

        # Songs mit audio_url ohne AudioAsset.
        orphan_songs: list[dict[str, Any]] = []
        if table_exists(con, "songs"):
            columns = table_columns(con, "songs")
            if "audio_url" in columns:
                where = ["audio_url IS NOT NULL", "TRIM(audio_url) <> ''"]
                if "is_deleted" in columns:
                    where.insert(0, "COALESCE(is_deleted, 0) = 0")
                for row in con.execute(f"SELECT id, title, task_id, audio_url FROM songs WHERE {' AND '.join(where)} ORDER BY id ASC").fetchall():
                    audio_url = row["audio_url"]
                    if not looks_like_audio_url(audio_url, key_hint="audio_url"):
                        continue
                    if not asset_match_exists(con, source_url=audio_url, audio_id=None, task_id=None, suno_task_id=row["task_id"]):
                        orphan_songs.append({"song_id": row["id"], "title": row["title"], "task_id": row["task_id"], "audio_url": audio_url})
        if orphan_songs:
            findings.append(AuditFinding("SONG_AUDIO_WITHOUT_ASSET", "high", len(orphan_songs), "Songs mit audio_url haben keinen aktiven AudioAsset-Eintrag.", orphan_songs[:20]))

        # AudioAsset-Datenqualität.
        if table_exists(con, "audio_assets"):
            columns = table_columns(con, "audio_assets")
            active_where = "COALESCE(is_deleted, 0) = 0" if "is_deleted" in columns else "1=1"
            bad_source = select_dicts(con, f"SELECT id, display_title, title, source_url, status FROM audio_assets WHERE {active_where} AND (source_url IS NULL OR TRIM(source_url) = '') ORDER BY id ASC LIMIT 20") if "source_url" in columns else []
            bad_source_count = int(con.execute(f"SELECT COUNT(*) FROM audio_assets WHERE {active_where} AND (source_url IS NULL OR TRIM(source_url) = '')").fetchone()[0]) if "source_url" in columns else 0
            if bad_source_count:
                findings.append(AuditFinding("ASSET_WITHOUT_SOURCE_URL", "critical", bad_source_count, "Aktive AudioAssets ohne source_url gefunden.", bad_source))

            if "source_url" in columns:
                dupes = select_dicts(con, f"SELECT source_url, COUNT(*) AS count, GROUP_CONCAT(id) AS ids FROM audio_assets WHERE {active_where} AND source_url IS NOT NULL AND TRIM(source_url) <> '' GROUP BY source_url HAVING COUNT(*) > 1 ORDER BY count DESC LIMIT 20")
                if dupes:
                    total = sum(int(row["count"]) - 1 for row in dupes)
                    findings.append(AuditFinding("DUPLICATE_SOURCE_URL", "medium", total, "Mehrere aktive AudioAssets mit identischer source_url.", dupes))
            if "audio_id" in columns:
                dupes_audio = select_dicts(con, f"SELECT audio_id, COUNT(*) AS count, GROUP_CONCAT(id) AS ids FROM audio_assets WHERE {active_where} AND audio_id IS NOT NULL AND TRIM(audio_id) <> '' GROUP BY audio_id HAVING COUNT(*) > 1 ORDER BY count DESC LIMIT 20")
                if dupes_audio:
                    total = sum(int(row["count"]) - 1 for row in dupes_audio)
                    findings.append(AuditFinding("DUPLICATE_AUDIO_ID", "medium", total, "Mehrere aktive AudioAssets mit identischer audio_id.", dupes_audio))
            if "local_path" in columns and "status" in columns:
                cached_without_file: list[dict[str, Any]] = []
                for row in con.execute(f"SELECT id, display_title, title, local_path, public_url, status FROM audio_assets WHERE {active_where} AND LOWER(COALESCE(status, '')) = 'cached' AND local_path IS NOT NULL AND TRIM(local_path) <> '' ORDER BY id DESC LIMIT 200").fetchall():
                    local_path = Path(row["local_path"])
                    check_path = local_path if local_path.is_absolute() else db_path.parent / local_path
                    if not check_path.exists():
                        cached_without_file.append(dict(row))
                if cached_without_file:
                    findings.append(AuditFinding("CACHED_FILE_MISSING", "medium", len(cached_without_file), "AudioAssets stehen auf cached, aber lokale Datei wurde nicht gefunden.", cached_without_file[:20]))

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings = sorted(findings, key=lambda item: (severity_order.get(item.severity, 99), item.code))
        return {
            "database": str(db_path),
            "integrity_check": integrity,
            "tables": tables,
            "counts": counts,
            "tasks_with_audio_candidates": tasks_with_candidates,
            "findings": [asdict(item) for item in findings],
        }
    finally:
        con.close()


def print_human(audit: dict[str, Any]) -> None:
    print("Unified-Audio Local Master Audit")
    print(f"Datenbank       : {audit['database']}")
    print(f"Integrity       : {audit['integrity_check']}")
    print("\nTabellen/Counts:")
    for table, count in audit["counts"].items():
        exists = "OK" if audit["tables"].get(table, True) else "FEHLT"
        print(f"  {table:<22} {count:>6}  {exists}")
    print(f"\nTasks mit Audio-Kandidaten: {audit['tasks_with_audio_candidates']}")
    findings = audit.get("findings", [])
    if not findings:
        print("\nKeine kritischen Unified-Audio-Abweichungen gefunden.")
        return
    print("\nBefunde:")
    for item in findings:
        print(f"  [{item['severity'].upper()}] {item['code']}: {item['count']} - {item['message']}")
        for sample in item.get("sample", [])[:3]:
            print(f"    Beispiel: {sample}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Prüft lokale Suno Song Studio DB auf Unified-Audio-Abweichungen. Verändert nichts.")
    parser.add_argument("--database", "--db", dest="database", default="", help="Pfad zur SQLite-DB oder sqlite:/// URL. Standard: DATABASE_URL oder ./suno_fastapi_app.db")
    parser.add_argument("--json", action="store_true", help="JSON statt Text ausgeben.")
    parser.add_argument("--fail-on-high", action="store_true", help="Exitcode 1 bei high/critical Befunden.")
    args = parser.parse_args()

    root = project_root()
    os.chdir(root)
    db_path = resolve_db_path(args.database)
    if not db_path.exists():
        print(f"ABBRUCH: Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 2
    audit = build_audit(db_path)
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        print_human(audit)
    if args.fail_on_high:
        for item in audit.get("findings", []):
            if item.get("severity") in {"critical", "high"}:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
