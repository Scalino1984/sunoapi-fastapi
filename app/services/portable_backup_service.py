from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.models import AppSetting, AudioAsset, AudioTranscript, DawPromptHook, LyricDraft, MusicStyle, Song, VideoAsset
from app.services.system_status_notification_service import create_system_status_notification
from app.services.portable_path_service import project_root, resolve_portable_path, to_portable_path
from app.utils.time_utils import utc_now_naive

logger = logging.getLogger("songstudio.portable_backup")
BACKUP_FORMAT = "suno-song-studio-portable-backup"
BACKUP_VERSION = 2
PORTABLE_BACKUP_SCHEDULE_KEY = "portable_backup_schedule"
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ProgressCallback = Callable[[str, str, int, int | None, int | None, dict[str, Any] | None], None]

FULL_STORAGE_SCOPE_KEYS = {"audio", "covers", "videos", "transcripts", "stems", "exports"}
PARTIAL_DATA_SCOPE_KEYS = {"lyrics", "styles", "daw_prompts"}
DEFAULT_BACKUP_SCOPES = {
    "database": True,
    "audio": True,
    "covers": True,
    "videos": True,
    "transcripts": True,
    "stems": True,
    "exports": True,
    "lyrics": True,
    "styles": True,
    "daw_prompts": True,
}


@dataclass(slots=True)
class PortablePathStats:
    checked: int = 0
    changed: int = 0
    absolute_before: int = 0
    missing_files: int = 0


@dataclass(slots=True)
class PortableBackupJob:
    id: str
    job_type: str
    status: str = "queued"
    phase: str = "queued"
    message: str = "Warte auf Start."
    percent: int = 0
    current: int | None = None
    total: int | None = None
    created_at: str = field(default_factory=lambda: utc_now_naive().isoformat())
    updated_at: str = field(default_factory=lambda: utc_now_naive().isoformat())
    completed_at: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    download_path: str | None = None
    download_filename: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["done"] = self.status in TERMINAL_JOB_STATUSES
        payload["download_ready"] = bool(self.download_path and self.status == "completed")
        if self.download_path:
            payload["download_exists"] = Path(self.download_path).exists()
        return payload


_jobs: dict[str, PortableBackupJob] = {}
_jobs_lock = threading.RLock()


def sqlite_database_path() -> Path:
    url = str(get_settings().database_url or "")
    if not url.startswith("sqlite"):
        raise RuntimeError("Portable Backup unterstützt aktuell nur SQLite-Datenbanken.")
    database = engine.url.database or "./suno_fastapi_app.db"
    return Path(database).expanduser().resolve()


def _utc_stamp() -> str:
    return utc_now_naive().strftime("%Y%m%d_%H%M%S")


def _human_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{value} B"


def _normalize_backup_mode(value: Any) -> str:
    normalized = str(value or "full").strip().lower()
    return "partial" if normalized in {"partial", "scoped", "selected"} else "full"


def normalize_backup_scopes(scopes: dict[str, Any] | None = None, *, mode: str = "full") -> dict[str, bool]:
    provided = scopes if isinstance(scopes, dict) else {}
    normalized = dict(DEFAULT_BACKUP_SCOPES)
    for key in normalized:
        if key in provided:
            normalized[key] = bool(provided.get(key))
    if _normalize_backup_mode(mode) == "partial":
        normalized["database"] = False
        for key in FULL_STORAGE_SCOPE_KEYS:
            normalized[key] = False
    return normalized


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _model_payload(row: Any, fields: list[str]) -> dict[str, Any]:
    payload = {"source_id": getattr(row, "id", None)}
    for field_name in fields:
        payload[field_name] = _json_safe(getattr(row, field_name, None))
    return payload


def _partial_export_data(db: Session, scopes: dict[str, bool]) -> dict[str, list[dict[str, Any]]]:
    data: dict[str, list[dict[str, Any]]] = {}
    if scopes.get("lyrics"):
        rows = db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(False)).order_by(LyricDraft.updated_at.desc()).all()
        data["lyrics"] = [
            _model_payload(row, ["title", "content", "status", "language", "tags", "structure_template", "metadata_json", "created_at", "updated_at"])
            for row in rows
        ]
    if scopes.get("styles"):
        rows = db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).order_by(MusicStyle.updated_at.desc()).all()
        data["styles"] = [
            _model_payload(row, ["name", "genre", "bpm", "style_text", "description", "tags", "is_favorite", "usage_count", "profile_json", "is_profile", "created_at", "updated_at"])
            for row in rows
        ]
    if scopes.get("daw_prompts"):
        rows = db.query(DawPromptHook).filter(DawPromptHook.is_deleted.is_(False)).order_by(DawPromptHook.scope.asc(), DawPromptHook.sort_order.asc(), DawPromptHook.title.asc()).all()
        data["daw_prompts"] = [
            _model_payload(row, ["title", "prompt", "description", "scope", "tags_json", "sort_order", "is_active", "metadata_json", "created_at", "updated_at"])
            for row in rows
        ]
    return data


def _norm_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _merge_metadata(existing: dict[str, Any] | None, imported: dict[str, Any] | None, source_id: Any = None) -> dict[str, Any]:
    merged = dict(existing or {})
    imported_meta = imported if isinstance(imported, dict) else {}
    for key, value in imported_meta.items():
        if key not in merged:
            merged[key] = value
    meta = dict(merged.get("portable_backup_import") or {})
    meta.update({"imported_at": utc_now_naive().isoformat(), "source_id": source_id})
    merged["portable_backup_import"] = meta
    return merged


def _partial_manifest(*, mode: str, scopes: dict[str, bool], note: str | None, automatic: bool = False) -> dict[str, Any]:
    settings = get_settings()
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "mode": mode,
        "scopes": scopes,
        "created_at": utc_now_naive().isoformat(),
        "automatic": automatic,
        "app": settings.app_name,
        "note": note or None,
    }


def _safe_zip_member(member: str) -> bool:
    path = Path(member)
    return not path.is_absolute() and ".." not in path.parts


def _safe_extract(zip_file: ZipFile, target_dir: Path, *, progress: ProgressCallback | None = None, percent_start: int = 0, percent_end: int = 100) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    members = [member for member in zip_file.infolist() if not member.is_dir()]
    total = max(1, len(members))
    for index, member in enumerate(members, start=1):
        if not _safe_zip_member(member.filename):
            raise ValueError(f"Unsicherer ZIP-Pfad: {member.filename}")
        destination = target_dir / member.filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zip_file.open(member, "r") as source, destination.open("wb") as sink:
            shutil.copyfileobj(source, sink)
        if progress and (index == total or index % 10 == 0 or index == 1):
            percent = percent_start + int((percent_end - percent_start) * (index / total))
            progress("extract", f"Backup wird entpackt: {index}/{total}", percent, index, total, None)


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return (path for path in root.rglob("*") if path.is_file())


def _sqlite_backup_to(destination: Path) -> None:
    source = sqlite_database_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(destination)) as dst:
        src.execute("PRAGMA wal_checkpoint(FULL)")
        src.backup(dst)


def _sqlite_restore_from(source: Path) -> None:
    target = sqlite_database_path()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Backup-Datenbank fehlt: {source}")
    engine.dispose()
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
        dst.execute("PRAGMA foreign_keys=OFF")
        src.backup(dst)
        dst.execute("PRAGMA foreign_keys=ON")
    engine.dispose()
    init_db()


def _storage_specs() -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {"key": "audio", "root": settings.audio_storage_path, "archive": "files/audio"},
        {"key": "covers", "root": settings.cover_storage_path, "archive": "files/covers"},
        {"key": "videos", "root": settings.video_storage_path, "archive": "files/videos"},
        {"key": "transcripts", "root": settings.transcript_storage_path, "archive": "files/transcripts"},
        {"key": "stems", "root": (project_root() / "storage" / "stems").resolve(), "archive": "files/stems"},
        {"key": "exports", "root": (project_root() / "storage" / "exports").resolve(), "archive": "files/exports"},
    ]


def _list_storage_files(scope_keys: set[str] | None = None) -> list[tuple[dict[str, Any], Path, str, int]]:
    rows: list[tuple[dict[str, Any], Path, str, int]] = []
    for spec in _storage_specs():
        if scope_keys is not None and str(spec["key"]) not in scope_keys:
            continue
        root = Path(spec["root"]).resolve()
        for path in _iter_files(root):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.name
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append((spec, path, rel, size))
    return rows


def _create_job(job_type: str) -> PortableBackupJob:
    job = PortableBackupJob(id=uuid4().hex, job_type=job_type)
    with _jobs_lock:
        _jobs[job.id] = job
        _cleanup_old_jobs_locked()
    return job


def _cleanup_old_jobs_locked() -> None:
    now = time.time()
    for job_id, job in list(_jobs.items()):
        if job.status not in TERMINAL_JOB_STATUSES:
            continue
        try:
            updated = datetime.fromisoformat(job.updated_at).timestamp()
        except Exception:
            updated = now
        if now - updated > 24 * 3600:
            _jobs.pop(job_id, None)


def _update_job(job_id: str, *, status: str | None = None, phase: str | None = None, message: str | None = None, percent: int | None = None, current: int | None = None, total: int | None = None, error: str | None = None, result: dict[str, Any] | None = None, download_path: Path | str | None = None, download_filename: str | None = None) -> PortableBackupJob | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if status is not None:
            job.status = status
            if status in TERMINAL_JOB_STATUSES:
                job.completed_at = utc_now_naive().isoformat()
        if phase is not None:
            job.phase = phase
        if message is not None:
            job.message = message
        if percent is not None:
            job.percent = max(0, min(100, int(percent)))
        job.current = current
        job.total = total
        if error is not None:
            job.error = error
        if result is not None:
            job.result = result
        if download_path is not None:
            job.download_path = str(download_path)
        if download_filename is not None:
            job.download_filename = download_filename
        job.updated_at = utc_now_naive().isoformat()
        return job




def _notify_portable_job(job_id: str, event_type: str, title: str, message: str, *, severity: str = "info", result: dict[str, Any] | None = None, error: str | None = None) -> None:
    payload = {
        "target_tab": "system",
        "section": "portable_backup",
        "job_id": job_id,
        "job_type": "portable_backup",
        "click_target": "system_portable_backup",
    }
    if result:
        payload["result"] = result
    if error:
        payload["error"] = error
    create_system_status_notification(
        None,
        event_type=event_type,
        title=title,
        message=message,
        severity=severity,
        target_tab="system",
        target_payload=payload,
        commit=True,
    )


def _job_progress(job_id: str) -> ProgressCallback:
    def callback(phase: str, message: str, percent: int, current: int | None = None, total: int | None = None, extra: dict[str, Any] | None = None) -> None:
        result = None
        if extra:
            result = {"last_progress": extra}
        _update_job(job_id, status="running", phase=phase, message=message, percent=percent, current=current, total=total, result=result)
    return callback


def get_portable_backup_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return job.as_dict()


def get_portable_backup_download(job_id: str) -> Path:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status != "completed" or not job.download_path:
            raise RuntimeError("Backup ist noch nicht zum Download bereit.")
        path = Path(job.download_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("Backup-Datei wurde nicht gefunden.")
        return path


def normalize_portable_paths(db: Session, *, dry_run: bool = False) -> dict[str, Any]:
    settings = get_settings()
    stats = {
        "audio_assets": PortablePathStats(),
        "songs": PortablePathStats(),
        "transcripts": PortablePathStats(),
        "cover_cache": PortablePathStats(),
        "videos": PortablePathStats(),
    }

    audio_roots = [settings.audio_storage_path]
    cover_roots = [settings.cover_storage_path]
    video_roots = [settings.video_storage_path]
    transcript_roots = [settings.transcript_storage_path]

    for asset in db.query(AudioAsset).all():
        stats["audio_assets"].checked += 1
        if asset.local_path:
            if Path(str(asset.local_path)).is_absolute():
                stats["audio_assets"].absolute_before += 1
            resolved = resolve_portable_path(asset.local_path, audio_roots)
            portable = to_portable_path(resolved or asset.local_path, storage_root=settings.audio_storage_path)
            if resolved is None:
                stats["audio_assets"].missing_files += 1
            if portable and portable != asset.local_path:
                stats["audio_assets"].changed += 1
                if not dry_run:
                    asset.local_path = portable
        metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else None
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("local_path"):
            stats["cover_cache"].checked += 1
            value = str(cover_cache.get("local_path"))
            if Path(value).is_absolute():
                stats["cover_cache"].absolute_before += 1
            resolved = resolve_portable_path(value, cover_roots)
            portable = to_portable_path(resolved or value, storage_root=settings.cover_storage_path)
            if resolved is None:
                stats["cover_cache"].missing_files += 1
            if portable and portable != value:
                stats["cover_cache"].changed += 1
                if not dry_run:
                    metadata = dict(metadata)
                    cover_cache = dict(cover_cache)
                    cover_cache["local_path"] = portable
                    metadata["cover_cache"] = cover_cache
                    asset.metadata_json = metadata

    for song in db.query(Song).all():
        metadata = song.metadata_json if isinstance(song.metadata_json, dict) else None
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("local_path"):
            stats["songs"].checked += 1
            value = str(cover_cache.get("local_path"))
            if Path(value).is_absolute():
                stats["songs"].absolute_before += 1
            resolved = resolve_portable_path(value, cover_roots)
            portable = to_portable_path(resolved or value, storage_root=settings.cover_storage_path)
            if resolved is None:
                stats["songs"].missing_files += 1
            if portable and portable != value:
                stats["songs"].changed += 1
                if not dry_run:
                    metadata = dict(metadata)
                    cover_cache = dict(cover_cache)
                    cover_cache["local_path"] = portable
                    metadata["cover_cache"] = cover_cache
                    song.metadata_json = metadata

    for video in db.query(VideoAsset).all():
        stats["videos"].checked += 1
        if video.local_path:
            if Path(str(video.local_path)).is_absolute():
                stats["videos"].absolute_before += 1
            resolved = resolve_portable_path(video.local_path, video_roots)
            portable = to_portable_path(resolved or video.local_path, storage_root=settings.video_storage_path)
            if resolved is None:
                stats["videos"].missing_files += 1
            if portable and portable != video.local_path:
                stats["videos"].changed += 1
                if not dry_run:
                    video.local_path = portable

    for transcript in db.query(AudioTranscript).all():
        stats["transcripts"].checked += 1
        if transcript.srt_path:
            if Path(str(transcript.srt_path)).is_absolute():
                stats["transcripts"].absolute_before += 1
            resolved = resolve_portable_path(transcript.srt_path, transcript_roots)
            portable = to_portable_path(resolved or transcript.srt_path, storage_root=settings.transcript_storage_path)
            if resolved is None:
                stats["transcripts"].missing_files += 1
            if portable and portable != transcript.srt_path:
                stats["transcripts"].changed += 1
                if not dry_run:
                    transcript.srt_path = portable

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "ok": True,
        "dry_run": dry_run,
        "stats": {key: asdict(value) for key, value in stats.items()},
    }


def create_portable_backup(
    db: Session,
    *,
    normalize_paths: bool = True,
    note: str | None = None,
    progress: ProgressCallback | None = None,
    scopes: dict[str, Any] | None = None,
    automatic: bool = False,
) -> Path:
    settings = get_settings()
    backup_dir = settings.backup_storage_path
    backup_dir.mkdir(parents=True, exist_ok=True)
    normalized_scopes = normalize_backup_scopes(scopes, mode="full")
    if normalize_paths:
        if progress:
            progress("normalize", "Portable Pfade werden normalisiert.", 3, None, None, None)
        normalize_portable_paths(db, dry_run=False)

    prefix = "suno_song_studio_auto_backup" if automatic else "suno_song_studio_portable_backup"
    filename = f"{prefix}_{_utc_stamp()}.zip"
    target = backup_dir / filename
    temp_dir = backup_dir / f".backup-build-{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_copy = temp_dir / "suno_fastapi_app.db"
    storage_keys = {key for key in FULL_STORAGE_SCOPE_KEYS if normalized_scopes.get(key)}
    storage_files = _list_storage_files(storage_keys)
    storage_total = max(1, len(storage_files))
    try:
        if progress:
            progress("database", "SQLite-Datenbank wird konsistent gesichert.", 8, 0, 1, None)
        _sqlite_backup_to(db_copy)
        manifest_files: dict[str, Any] = {}
        with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as zip_file:
            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "mode": "full",
                "automatic": automatic,
                "scopes": normalized_scopes,
                "created_at": utc_now_naive().isoformat(),
                "app": settings.app_name,
                "note": note or None,
                "database": {"path": "database/suno_fastapi_app.db", "size_bytes": db_copy.stat().st_size},
                "storage": {},
                "settings": {
                    "audio_public_route": settings.suno_audio_public_route,
                    "cover_public_route": settings.suno_cover_public_route,
                    "audio_cache_mode": settings.suno_audio_cache_mode,
                    "local_content_storage_enabled": settings.local_content_storage_enabled,
                },
            }
            if progress:
                progress("zip_database", "Datenbank wird ins Backup-ZIP geschrieben.", 12, 1, storage_total + 1, None)
            zip_file.write(db_copy, "database/suno_fastapi_app.db")
            total_files = 1
            total_bytes = db_copy.stat().st_size
            per_storage: dict[str, dict[str, int]] = {spec["key"]: {"files": 0, "size_bytes": 0} for spec in _storage_specs()}
            for index, (spec, path, rel, file_size) in enumerate(storage_files, start=1):
                archive_root = spec["archive"]
                arcname = f"{archive_root}/{rel}"
                zip_file.write(path, arcname)
                count_data = per_storage.setdefault(spec["key"], {"files": 0, "size_bytes": 0})
                count_data["files"] += 1
                count_data["size_bytes"] += file_size
                total_files += 1
                total_bytes += file_size
                if progress and (index == 1 or index == storage_total or index % 10 == 0):
                    percent = 12 + int(80 * (index / storage_total))
                    progress("zip_files", f"Lokale Dateien werden gepackt: {index}/{storage_total}", percent, index, storage_total, {"current_file": str(path.name)})
            for spec in _storage_specs():
                if str(spec["key"]) not in storage_keys:
                    continue
                data = per_storage.get(spec["key"], {"files": 0, "size_bytes": 0})
                manifest["storage"][spec["key"]] = {"archive_root": spec["archive"], "files": data["files"], "size_bytes": data["size_bytes"]}
            manifest["total"] = {"files": total_files, "size_bytes": total_bytes, "human_size": _human_bytes(total_bytes)}
            if progress:
                progress("manifest", "Manifest wird geschrieben.", 96, total_files, total_files, None)
            zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if progress:
            progress("completed", "Portables Backup wurde fertig erstellt.", 100, storage_total, storage_total, {"filename": target.name, "size_bytes": target.stat().st_size})
        return target
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def create_scoped_portable_backup(
    db: Session,
    *,
    scopes: dict[str, Any] | None = None,
    note: str | None = None,
    progress: ProgressCallback | None = None,
    automatic: bool = False,
) -> Path:
    settings = get_settings()
    backup_dir = settings.backup_storage_path
    backup_dir.mkdir(parents=True, exist_ok=True)
    normalized_scopes = normalize_backup_scopes(scopes, mode="partial")
    selected_data_scopes = [key for key in sorted(PARTIAL_DATA_SCOPE_KEYS) if normalized_scopes.get(key)]
    if not selected_data_scopes:
        raise ValueError("Für ein Teilbackup muss mindestens Songtexte, Styles oder DAW-Prompts aktiviert sein.")
    prefix = "suno_song_studio_auto_partial_backup" if automatic else "suno_song_studio_portable_partial_backup"
    target = backup_dir / f"{prefix}_{_utc_stamp()}.zip"
    if progress:
        progress("collect", "Ausgewählte Daten werden gesammelt.", 10, None, None, {"scopes": selected_data_scopes})
    data = _partial_export_data(db, normalized_scopes)
    total_items = sum(len(items) for items in data.values())
    manifest = _partial_manifest(mode="partial", scopes=normalized_scopes, note=note, automatic=automatic)
    manifest["data"] = {key: {"path": f"data/{key}.json", "items": len(items)} for key, items in data.items()}
    manifest["total"] = {"items": total_items}
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as zip_file:
        for index, (key, items) in enumerate(data.items(), start=1):
            zip_file.writestr(f"data/{key}.json", json.dumps(items, ensure_ascii=False, indent=2))
            if progress:
                percent = 10 + int(75 * (index / max(1, len(data))))
                progress("write_data", f"{key} wird geschrieben: {len(items)} Einträge.", percent, index, len(data), {"scope": key})
        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    if progress:
        progress("completed", "Teilbackup wurde fertig erstellt.", 100, total_items, total_items, {"filename": target.name, "size_bytes": target.stat().st_size})
    return target


def inspect_portable_backup(backup_path: Path) -> dict[str, Any]:
    with ZipFile(backup_path, "r") as zip_file:
        names = set(zip_file.namelist())
        if "manifest.json" not in names:
            raise ValueError("manifest.json fehlt im Backup.")
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("Backup-Format passt nicht zu Suno Song Studio Portable Backup.")
        mode = _normalize_backup_mode(manifest.get("mode") or "full")
        if mode == "full" and "database/suno_fastapi_app.db" not in names:
            raise ValueError("database/suno_fastapi_app.db fehlt im Backup.")
        return {"ok": True, "manifest": manifest, "zip_entries": len(names)}


def _read_partial_json(zip_file: ZipFile, name: str) -> list[dict[str, Any]]:
    if name not in zip_file.namelist():
        return []
    payload = json.loads(zip_file.read(name).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{name} muss eine JSON-Liste enthalten.")
    return [item for item in payload if isinstance(item, dict)]


def _import_partial_portable_backup(backup_path: Path, db: Session, inspection: dict[str, Any], *, progress: ProgressCallback | None = None) -> dict[str, Any]:
    if progress:
        progress("merge", "Teilbackup wird eingelesen.", 20, None, None, None)
    imported = {"lyrics": 0, "styles": 0, "daw_prompts": 0}
    updated = {"lyrics": 0, "styles": 0, "daw_prompts": 0}
    skipped = {"lyrics": 0, "styles": 0, "daw_prompts": 0}
    with ZipFile(backup_path, "r") as zip_file:
        lyrics_rows = _read_partial_json(zip_file, "data/lyrics.json")
        style_rows = _read_partial_json(zip_file, "data/styles.json")
        prompt_rows = _read_partial_json(zip_file, "data/daw_prompts.json")

    total = max(1, len(lyrics_rows) + len(style_rows) + len(prompt_rows))
    current = 0

    for row in lyrics_rows:
        current += 1
        title = str(row.get("title") or "").strip()
        content = str(row.get("content") or "")
        if not title or not content:
            skipped["lyrics"] += 1
            continue
        existing = db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(False), LyricDraft.title == title, LyricDraft.content == content).first()
        if existing:
            existing.status = str(row.get("status") or existing.status or "draft")
            existing.language = row.get("language") or existing.language
            existing.tags = row.get("tags") if row.get("tags") is not None else existing.tags
            existing.structure_template = row.get("structure_template") if row.get("structure_template") is not None else existing.structure_template
            existing.metadata_json = _merge_metadata(existing.metadata_json, row.get("metadata_json"), row.get("source_id"))
            updated["lyrics"] += 1
        else:
            db.add(LyricDraft(
                title=title[:255],
                content=content,
                status=str(row.get("status") or "draft")[:80],
                language=(str(row.get("language"))[:40] if row.get("language") else None),
                tags=row.get("tags"),
                structure_template=(str(row.get("structure_template"))[:120] if row.get("structure_template") else None),
                metadata_json=_merge_metadata(None, row.get("metadata_json"), row.get("source_id")),
            ))
            imported["lyrics"] += 1
        if progress and (current == total or current % 20 == 0):
            progress("merge", f"Teilbackup wird importiert: {current}/{total}", 20 + int(70 * (current / total)), current, total, None)

    existing_styles = {
        (_norm_key(style.name), _norm_key(style.style_text)): style
        for style in db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).all()
    }
    for row in style_rows:
        current += 1
        name = str(row.get("name") or "").strip()
        style_text = str(row.get("style_text") or "").strip()
        if not name or not style_text:
            skipped["styles"] += 1
            continue
        existing = existing_styles.get((_norm_key(name), _norm_key(style_text)))
        if existing:
            existing.genre = row.get("genre") if row.get("genre") is not None else existing.genre
            existing.bpm = row.get("bpm") if row.get("bpm") is not None else existing.bpm
            existing.description = row.get("description") if row.get("description") is not None else existing.description
            existing.tags = row.get("tags") if row.get("tags") is not None else existing.tags
            existing.is_favorite = bool(row.get("is_favorite", existing.is_favorite))
            existing.is_profile = bool(row.get("is_profile", existing.is_profile))
            existing.profile_json = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else existing.profile_json
            updated["styles"] += 1
        else:
            style = MusicStyle(
                name=name[:255],
                genre=(str(row.get("genre"))[:120] if row.get("genre") else None),
                bpm=row.get("bpm") if isinstance(row.get("bpm"), int) else None,
                style_text=style_text,
                description=row.get("description"),
                tags=row.get("tags"),
                is_favorite=bool(row.get("is_favorite", False)),
                usage_count=int(row.get("usage_count") or 0),
                profile_json=row.get("profile_json") if isinstance(row.get("profile_json"), dict) else None,
                is_profile=bool(row.get("is_profile", False)),
            )
            db.add(style)
            existing_styles[(_norm_key(name), _norm_key(style_text))] = style
            imported["styles"] += 1
        if progress and (current == total or current % 20 == 0):
            progress("merge", f"Teilbackup wird importiert: {current}/{total}", 20 + int(70 * (current / total)), current, total, None)

    existing_prompts = {
        (_norm_key(hook.scope), _norm_key(hook.title), _norm_key(hook.prompt)): hook
        for hook in db.query(DawPromptHook).filter(DawPromptHook.is_deleted.is_(False)).all()
    }
    for row in prompt_rows:
        current += 1
        title = str(row.get("title") or "").strip()
        prompt = str(row.get("prompt") or "").strip()
        scope = str(row.get("scope") or "daw").strip() or "daw"
        if not title or not prompt:
            skipped["daw_prompts"] += 1
            continue
        existing = existing_prompts.get((_norm_key(scope), _norm_key(title), _norm_key(prompt)))
        if existing:
            existing.description = row.get("description") if row.get("description") is not None else existing.description
            existing.tags_json = row.get("tags_json") if isinstance(row.get("tags_json"), list) else existing.tags_json
            existing.sort_order = int(row.get("sort_order") or existing.sort_order or 0)
            existing.is_active = bool(row.get("is_active", existing.is_active))
            existing.metadata_json = _merge_metadata(existing.metadata_json, row.get("metadata_json"), row.get("source_id"))
            updated["daw_prompts"] += 1
        else:
            hook = DawPromptHook(
                title=title[:180],
                prompt=prompt,
                description=row.get("description"),
                scope=scope[:80],
                tags_json=row.get("tags_json") if isinstance(row.get("tags_json"), list) else [],
                sort_order=int(row.get("sort_order") or 0),
                is_active=bool(row.get("is_active", True)),
                metadata_json=_merge_metadata(None, row.get("metadata_json"), row.get("source_id")),
            )
            db.add(hook)
            existing_prompts[(_norm_key(scope), _norm_key(title), _norm_key(prompt))] = hook
            imported["daw_prompts"] += 1
        if progress and (current == total or current % 20 == 0):
            progress("merge", f"Teilbackup wird importiert: {current}/{total}", 20 + int(70 * (current / total)), current, total, None)

    db.commit()
    result = {
        "ok": True,
        "mode": "partial",
        "imported_at": utc_now_naive().isoformat(),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "manifest": inspection["manifest"],
    }
    if progress:
        progress("completed", "Teilbackup wurde importiert.", 100, total, total, result)
    return result


def import_portable_backup(backup_path: Path, *, create_pre_import_backup: bool = True, db: Session | None = None, progress: ProgressCallback | None = None) -> dict[str, Any]:
    settings = get_settings()
    if progress:
        progress("inspect", "Backup-ZIP wird geprüft.", 2, None, None, None)
    inspection = inspect_portable_backup(backup_path)
    mode = _normalize_backup_mode((inspection.get("manifest") or {}).get("mode") or "full")
    if mode == "partial":
        if db is None:
            raise RuntimeError("Für den Teilbackup-Import wird eine DB-Session benötigt.")
        try:
            return _import_partial_portable_backup(backup_path, db, inspection, progress=progress)
        finally:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass

    pre_backup: str | None = None
    if create_pre_import_backup:
        if db is None:
            raise RuntimeError("Für das automatische Vorher-Backup wird eine DB-Session benötigt.")
        if progress:
            progress("pre_backup", "Vor Import wird der aktuelle Ist-Stand gesichert.", 5, None, None, None)
        def pre_progress(phase: str, message: str, percent: int, current: int | None, total: int | None, extra: dict[str, Any] | None) -> None:
            mapped = 5 + int(25 * (percent / 100))
            if progress:
                progress("pre_backup", f"Vorher-Backup: {message}", mapped, current, total, extra)
        pre_backup = str(create_portable_backup(db, normalize_paths=True, note="Automatisches Backup vor Portable-Import", progress=pre_progress))
        try:
            db.close()
        except Exception:
            pass

    import_root = settings.backup_storage_path / f".portable-import-{uuid4().hex}"
    try:
        with ZipFile(backup_path, "r") as zip_file:
            _safe_extract(zip_file, import_root, progress=progress, percent_start=32, percent_end=52)
        source_db = import_root / "database" / "suno_fastapi_app.db"

        file_rows: list[tuple[dict[str, Any], Path, Path]] = []
        for spec in _storage_specs():
            target_root = Path(spec["root"]).resolve()
            archive_root = import_root / str(spec["archive"])
            if archive_root.exists():
                for path in archive_root.rglob("*"):
                    if path.is_file():
                        file_rows.append((spec, archive_root, path))
        total_files = max(1, len(file_rows))
        if progress:
            progress("replace_files", "Lokale Zielordner werden vorbereitet.", 55, 0, total_files, None)

        for spec in _storage_specs():
            target_root = Path(spec["root"]).resolve()
            target_root.mkdir(parents=True, exist_ok=True)
            for child in list(target_root.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)

        for index, (spec, archive_root, path) in enumerate(file_rows, start=1):
            target_root = Path(spec["root"]).resolve()
            rel = path.relative_to(archive_root)
            destination = target_root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            if progress and (index == 1 or index == total_files or index % 10 == 0):
                percent = 55 + int(25 * (index / total_files))
                progress("replace_files", f"Lokale Dateien werden übernommen: {index}/{total_files}", percent, index, total_files, {"current_file": str(rel)})

        if progress:
            progress("restore_database", "SQLite-Datenbank wird wiederhergestellt.", 86, None, None, None)
        _sqlite_restore_from(source_db)
        result = {
            "ok": True,
            "imported_at": utc_now_naive().isoformat(),
            "pre_import_backup": pre_backup,
            "manifest": inspection["manifest"],
        }
        if progress:
            progress("completed", "Portable Backup wurde importiert.", 100, total_files, total_files, {"pre_import_backup": pre_backup})
        return result
    finally:
        shutil.rmtree(import_root, ignore_errors=True)
        try:
            backup_path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_export_job(job_id: str, *, normalize_paths: bool, note: str | None, mode: str = "full", scopes: dict[str, Any] | None = None, automatic: bool = False) -> None:
    db = SessionLocal()
    try:
        _update_job(job_id, status="running", phase="start", message="Export wird vorbereitet.", percent=1)
        normalized_mode = _normalize_backup_mode(mode)
        if normalized_mode == "partial":
            path = create_scoped_portable_backup(db, scopes=scopes, note=note, progress=_job_progress(job_id), automatic=automatic)
        else:
            path = create_portable_backup(db, normalize_paths=normalize_paths, note=note, progress=_job_progress(job_id), scopes=scopes, automatic=automatic)
        result_payload = {"filename": path.name, "size_bytes": path.stat().st_size, "size_human": _human_bytes(path.stat().st_size), "mode": normalized_mode, "automatic": automatic}
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            message="Portables Backup ist bereit zum Download.",
            percent=100,
            result=result_payload,
            download_path=path,
            download_filename=path.name,
        )
        _notify_portable_job(
            job_id,
            "portable_backup_export_completed",
            "Portables Backup bereit",
            f"Backup wurde erstellt: {path.name}",
            severity="success",
            result=result_payload,
        )
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc)
        _update_job(job_id, status="failed", phase="failed", message="Export fehlgeschlagen.", percent=100, error=error_text)
        _notify_portable_job(
            job_id,
            "portable_backup_export_failed",
            "Portables Backup fehlgeschlagen",
            error_text,
            severity="error",
            error=error_text,
        )
    finally:
        db.close()


def _run_import_job(job_id: str, import_path: Path) -> None:
    db = SessionLocal()
    try:
        _update_job(job_id, status="running", phase="start", message="Import wird vorbereitet.", percent=1)
        result = import_portable_backup(import_path, create_pre_import_backup=True, db=db, progress=_job_progress(job_id))
        _update_job(job_id, status="completed", phase="completed", message="Portable Backup wurde importiert.", percent=100, result=result)
        _notify_portable_job(
            job_id,
            "portable_backup_import_completed",
            "Portable-Backup-Import abgeschlossen",
            "Datenbank und lokale Dateien wurden aus dem portablen Backup übernommen.",
            severity="success",
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc)
        _update_job(job_id, status="failed", phase="failed", message="Import fehlgeschlagen.", percent=100, error=error_text)
        _notify_portable_job(
            job_id,
            "portable_backup_import_failed",
            "Portable-Backup-Import fehlgeschlagen",
            error_text,
            severity="error",
            error=error_text,
        )
        try:
            import_path.unlink(missing_ok=True)
        except OSError:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def start_portable_backup_export_job(
    *,
    normalize_paths: bool = True,
    note: str | None = None,
    mode: str = "full",
    scopes: dict[str, Any] | None = None,
    automatic: bool = False,
) -> dict[str, Any]:
    job = _create_job("portable_export")
    _notify_portable_job(
        job.id,
        "portable_backup_export_started",
        "Portables Backup gestartet",
        "Der Export der lokalen Datenbank und Dateien wurde gestartet.",
        severity="info",
    )
    thread = threading.Thread(
        target=_run_export_job,
        args=(job.id,),
        kwargs={"normalize_paths": normalize_paths, "note": note, "mode": mode, "scopes": scopes, "automatic": automatic},
        daemon=True,
    )
    thread.start()
    return get_portable_backup_job(job.id)


def start_portable_backup_import_job(import_path: Path) -> dict[str, Any]:
    job = _create_job("portable_import")
    _notify_portable_job(
        job.id,
        "portable_backup_import_started",
        "Portable-Backup-Import gestartet",
        "Ein portables Backup wird geprüft und importiert.",
        severity="warning",
    )
    thread = threading.Thread(target=_run_import_job, args=(job.id, import_path), daemon=True)
    thread.start()
    return get_portable_backup_job(job.id)


def _default_schedule() -> dict[str, Any]:
    return {
        "enabled": False,
        "frequency": "daily",
        "time": "03:00",
        "weekday": "sunday",
        "month_day": 1,
        "timezone": "Europe/Berlin",
        "retention_count": 14,
        "normalize_paths": True,
        "mode": "full",
        "scopes": dict(DEFAULT_BACKUP_SCOPES),
        "last_run_at": None,
        "next_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_backup": None,
    }


def _schedule_row(db: Session) -> AppSetting:
    row = db.query(AppSetting).filter(AppSetting.key == PORTABLE_BACKUP_SCHEDULE_KEY).first()
    if row:
        return row
    row = AppSetting(key=PORTABLE_BACKUP_SCHEDULE_KEY, value=_default_schedule(), description="Automatische Portable-Backup-Konfiguration")
    db.add(row)
    db.flush()
    return row


def _weekday_index(value: Any) -> int:
    mapping = {
        "monday": 0, "montag": 0, "mon": 0,
        "tuesday": 1, "dienstag": 1, "tue": 1,
        "wednesday": 2, "mittwoch": 2, "wed": 2,
        "thursday": 3, "donnerstag": 3, "thu": 3,
        "friday": 4, "freitag": 4, "fri": 4,
        "saturday": 5, "samstag": 5, "sat": 5,
        "sunday": 6, "sonntag": 6, "sun": 6,
    }
    return mapping.get(str(value or "sunday").strip().lower(), 6)


def _parse_time(value: Any) -> tuple[int, int]:
    text = str(value or "03:00").strip()
    try:
        hour_text, minute_text = text.split(":", 1)
        return max(0, min(23, int(hour_text))), max(0, min(59, int(minute_text)))
    except Exception:
        return 3, 0


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _next_schedule_run(settings_value: dict[str, Any], *, now: datetime | None = None) -> str | None:
    if not settings_value.get("enabled"):
        return None
    tz_name = str(settings_value.get("timezone") or "Europe/Berlin")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Berlin")
    current = now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=timezone.utc).astimezone(tz) if now else datetime.now(tz))
    hour, minute = _parse_time(settings_value.get("time"))
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    frequency = str(settings_value.get("frequency") or "daily").strip().lower()
    if frequency == "weekly":
        target_weekday = _weekday_index(settings_value.get("weekday"))
        days = (target_weekday - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=days)
        if candidate <= current:
            candidate = candidate + timedelta(days=7)
    elif frequency == "monthly":
        day = _safe_int(settings_value.get("month_day"), 1, 1, 28)
        candidate = candidate.replace(day=day)
        if candidate <= current:
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            candidate = candidate.replace(year=year, month=month, day=day)
    else:
        if candidate <= current:
            candidate = candidate + timedelta(days=1)
    return candidate.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat()


def _sanitize_schedule(payload: dict[str, Any] | None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _default_schedule()
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(payload, dict):
        merged.update({key: value for key, value in payload.items() if key in merged})
    frequency = str(merged.get("frequency") or "daily").strip().lower()
    merged["frequency"] = frequency if frequency in {"daily", "weekly", "monthly"} else "daily"
    hour, minute = _parse_time(merged.get("time"))
    merged["time"] = f"{hour:02d}:{minute:02d}"
    merged["weekday"] = str(merged.get("weekday") or "sunday").strip().lower()
    merged["month_day"] = _safe_int(merged.get("month_day"), 1, 1, 28)
    merged["retention_count"] = _safe_int(merged.get("retention_count"), 14, 1, 365)
    merged["enabled"] = bool(merged.get("enabled"))
    merged["normalize_paths"] = bool(merged.get("normalize_paths", True))
    merged["mode"] = _normalize_backup_mode(merged.get("mode"))
    merged["scopes"] = normalize_backup_scopes(merged.get("scopes") if isinstance(merged.get("scopes"), dict) else None, mode=merged["mode"])
    merged["next_run_at"] = _next_schedule_run(merged)
    return merged


def get_portable_backup_schedule(db: Session) -> dict[str, Any]:
    row = _schedule_row(db)
    value = _sanitize_schedule(None, row.value if isinstance(row.value, dict) else None)
    row.value = value
    db.commit()
    return value


def update_portable_backup_schedule(db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    row = _schedule_row(db)
    value = _sanitize_schedule(payload or {}, row.value if isinstance(row.value, dict) else None)
    row.value = value
    db.commit()
    return value


def rotate_auto_portable_backups(retention_count: int) -> dict[str, Any]:
    backup_dir = get_settings().backup_storage_path
    backup_dir.mkdir(parents=True, exist_ok=True)
    patterns = ["suno_song_studio_auto_backup_*.zip", "suno_song_studio_auto_partial_backup_*.zip"]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(backup_dir.glob(pattern))
    sorted_paths = sorted({path for path in paths if path.is_file()}, key=lambda item: item.stat().st_mtime, reverse=True)
    keep = max(1, int(retention_count or 1))
    deleted = []
    for path in sorted_paths[keep:]:
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            logger.exception("Auto-Backup konnte nicht rotiert werden: %s", path)
    return {"ok": True, "kept": min(len(sorted_paths), keep), "deleted": deleted}


def run_scheduled_portable_backup_once(db: Session, *, force: bool = False) -> dict[str, Any]:
    row = _schedule_row(db)
    schedule = _sanitize_schedule(None, row.value if isinstance(row.value, dict) else None)
    now = utc_now_naive()
    due = bool(force)
    if schedule.get("enabled") and schedule.get("next_run_at"):
        try:
            due = due or datetime.fromisoformat(str(schedule["next_run_at"])) <= now
        except Exception:
            due = True
    if not due:
        return {"ok": True, "ran": False, "schedule": schedule}
    try:
        mode = _normalize_backup_mode(schedule.get("mode"))
        note = "Automatisches Portable Backup"
        if mode == "partial":
            backup_path = create_scoped_portable_backup(db, scopes=schedule.get("scopes"), note=note, automatic=True)
        else:
            backup_path = create_portable_backup(
                db,
                normalize_paths=bool(schedule.get("normalize_paths", True)),
                note=note,
                scopes=schedule.get("scopes"),
                automatic=True,
            )
        rotation = rotate_auto_portable_backups(int(schedule.get("retention_count") or 14))
        schedule.update({
            "last_run_at": now.isoformat(),
            "last_status": "completed",
            "last_error": None,
            "last_backup": backup_path.name,
            "next_run_at": _next_schedule_run(schedule, now=now),
        })
        row.value = schedule
        db.commit()
        create_system_status_notification(
            None,
            event_type="portable_backup_auto_completed",
            title="Automatisches Backup erstellt",
            message=f"Auto-Backup ist bereit: {backup_path.name}",
            severity="success",
            target_tab="system",
            target_payload={"target_tab": "system", "section": "portable_backup", "filename": backup_path.name, "rotation": rotation, "click_target": "system_portable_backup"},
            commit=True,
        )
        return {"ok": True, "ran": True, "backup": backup_path.name, "rotation": rotation, "schedule": schedule}
    except Exception as exc:  # noqa: BLE001
        schedule.update({
            "last_run_at": now.isoformat(),
            "last_status": "failed",
            "last_error": str(exc),
            "next_run_at": _next_schedule_run(schedule, now=now),
        })
        row.value = schedule
        db.commit()
        create_system_status_notification(
            None,
            event_type="portable_backup_auto_failed",
            title="Automatisches Backup fehlgeschlagen",
            message=str(exc),
            severity="error",
            target_tab="system",
            target_payload={"target_tab": "system", "section": "portable_backup", "error": str(exc), "click_target": "system_portable_backup"},
            commit=True,
        )
        raise


async def run_portable_backup_scheduler() -> None:
    await asyncio.sleep(45)
    while True:
        db = SessionLocal()
        try:
            run_scheduled_portable_backup_once(db)
        except asyncio.CancelledError:
            db.close()
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Auto-Backup-Scheduler fehlgeschlagen: %s", exc)
        finally:
            db.close()
        await asyncio.sleep(60)


def portable_backup_status(db: Session) -> dict[str, Any]:
    settings = get_settings()
    path_counts = normalize_portable_paths(db, dry_run=True)
    backup_dir = settings.backup_storage_path
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups = []
    for path in sorted(backup_dir.glob("suno_song_studio_portable_backup_*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
        stat = path.stat()
        backups.append({
            "filename": path.name,
            "size_bytes": stat.st_size,
            "size_human": _human_bytes(stat.st_size),
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    storage = []
    for spec in _storage_specs():
        root = Path(spec["root"]).resolve()
        files = list(_iter_files(root)) if root.exists() else []
        storage.append({"key": spec["key"], "path": str(root), "files": len(files), "size_bytes": sum(path.stat().st_size for path in files)})
    with _jobs_lock:
        recent_jobs = [job.as_dict() for job in sorted(_jobs.values(), key=lambda item: item.updated_at, reverse=True)[:10]]
    return {
        "ok": True,
        "backup_dir": str(backup_dir),
        "database": str(sqlite_database_path()),
        "local_content_storage_enabled": settings.local_content_storage_enabled,
        "audio_cache_mode": settings.suno_audio_cache_mode,
        "portable_path_check": path_counts,
        "storage": storage,
        "backups": backups,
        "jobs": recent_jobs,
        "schedule": get_portable_backup_schedule(db),
    }
