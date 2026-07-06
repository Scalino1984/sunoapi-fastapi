from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.models import AudioAsset, AudioTranscript, Song, VideoAsset
from app.services.system_status_notification_service import create_system_status_notification
from app.services.portable_path_service import project_root, resolve_portable_path, to_portable_path
from app.utils.time_utils import utc_now_naive

BACKUP_FORMAT = "suno-song-studio-portable-backup"
BACKUP_VERSION = 1
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ProgressCallback = Callable[[str, str, int, int | None, int | None, dict[str, Any] | None], None]


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


def _list_storage_files() -> list[tuple[dict[str, Any], Path, str, int]]:
    rows: list[tuple[dict[str, Any], Path, str, int]] = []
    for spec in _storage_specs():
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


def create_portable_backup(db: Session, *, normalize_paths: bool = True, note: str | None = None, progress: ProgressCallback | None = None) -> Path:
    settings = get_settings()
    backup_dir = settings.backup_storage_path
    backup_dir.mkdir(parents=True, exist_ok=True)
    if normalize_paths:
        if progress:
            progress("normalize", "Portable Pfade werden normalisiert.", 3, None, None, None)
        normalize_portable_paths(db, dry_run=False)

    filename = f"suno_song_studio_portable_backup_{_utc_stamp()}.zip"
    target = backup_dir / filename
    temp_dir = backup_dir / f".backup-build-{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_copy = temp_dir / "suno_fastapi_app.db"
    storage_files = _list_storage_files()
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


def inspect_portable_backup(backup_path: Path) -> dict[str, Any]:
    with ZipFile(backup_path, "r") as zip_file:
        names = set(zip_file.namelist())
        if "manifest.json" not in names:
            raise ValueError("manifest.json fehlt im Backup.")
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("Backup-Format passt nicht zu Suno Song Studio Portable Backup.")
        if "database/suno_fastapi_app.db" not in names:
            raise ValueError("database/suno_fastapi_app.db fehlt im Backup.")
        return {"ok": True, "manifest": manifest, "zip_entries": len(names)}


def import_portable_backup(backup_path: Path, *, create_pre_import_backup: bool = True, db: Session | None = None, progress: ProgressCallback | None = None) -> dict[str, Any]:
    settings = get_settings()
    if progress:
        progress("inspect", "Backup-ZIP wird geprüft.", 2, None, None, None)
    inspection = inspect_portable_backup(backup_path)
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


def _run_export_job(job_id: str, *, normalize_paths: bool, note: str | None) -> None:
    db = SessionLocal()
    try:
        _update_job(job_id, status="running", phase="start", message="Export wird vorbereitet.", percent=1)
        path = create_portable_backup(db, normalize_paths=normalize_paths, note=note, progress=_job_progress(job_id))
        result_payload = {"filename": path.name, "size_bytes": path.stat().st_size, "size_human": _human_bytes(path.stat().st_size)}
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


def start_portable_backup_export_job(*, normalize_paths: bool = True, note: str | None = None) -> dict[str, Any]:
    job = _create_job("portable_export")
    _notify_portable_job(
        job.id,
        "portable_backup_export_started",
        "Portables Backup gestartet",
        "Der Export der lokalen Datenbank und Dateien wurde gestartet.",
        severity="info",
    )
    thread = threading.Thread(target=_run_export_job, args=(job.id,), kwargs={"normalize_paths": normalize_paths, "note": note}, daemon=True)
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
    }
