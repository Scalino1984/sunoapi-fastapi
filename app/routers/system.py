from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine, get_db
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.audio_asset_repair_service import repair_audio_library, is_bad_image_asset
from app.services.task_lifecycle_service import recover_stale_tasks
from app.services.database_maintenance_service import inspect_database_maintenance, run_database_maintenance
from app.services.cover_cache_maintenance_service import cache_external_cover_references
from app.services.system_status_notification_service import create_system_status_notification
from app.services.portable_path_service import to_portable_path
from app.services.portable_backup_service import (
    create_portable_backup,
    create_scoped_portable_backup,
    get_portable_backup_download,
    get_portable_backup_job,
    get_portable_backup_schedule,
    import_portable_backup,
    normalize_portable_paths,
    portable_backup_status,
    run_scheduled_portable_backup_once,
    start_portable_backup_export_job,
    start_portable_backup_import_job,
    update_portable_backup_schedule,
)
from app.models import (
    AudioAsset,
    AudioProject,
    LyricDraft,
    MusicStyle,
    Persona,
    Playlist,
    PlaylistItem,
    ProductionProfile,
    Song,
    SunoTask,
    UploadedFileRecord,
    ActivityLog,
    User,
)
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/system", tags=["system"])
settings = get_settings()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _model_to_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: _serialize_value(getattr(row, column.name))
        for column in row.__table__.columns
    }


def _safe_config() -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "debug": settings.debug,
        "suno_base_url": settings.suno_base_url,
        "suno_file_upload_base_url": settings.suno_file_upload_base_url,
        "suno_api_key_configured": bool(settings.suno_api_key),
        "database_url": settings.database_url,
        "public_base_url": settings.public_base_url,
        "callback_url": settings.callback_url,
        "polling_interval_seconds": settings.polling_interval_seconds,
        "polling_max_attempts": settings.polling_max_attempts,
        "lyrics_prompt_max_length": settings.suno_lyrics_prompt_max_length,
        "model_limits": settings.model_limits,
        "audio_cache": {
            "mode": settings.suno_audio_cache_mode,
            "storage_dir": settings.suno_audio_storage_dir,
            "storage_path": str(settings.audio_storage_path),
            "public_route": settings.suno_audio_public_route,
            "download_timeout_seconds": settings.suno_audio_download_timeout_seconds,
            "max_download_mb": settings.suno_audio_max_download_mb,
            "allowed_extensions": settings.audio_allowed_extensions_list,
            "auto_download_only_music": settings.suno_auto_download_only_music,
        },
    }


def _safe_filename(value: str | None, fallback: str) -> str:
    raw = (value or fallback or "export").strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    return safe[:160].strip("._") or fallback


def _operation_from_asset(asset: AudioAsset) -> str:
    explicit = (asset.operation_label or "").strip().lower()
    if explicit:
        return explicit
    payload = asset.metadata_json or {}
    text = " ".join(str(v).lower() for v in [asset.display_title, asset.title, asset.parent_audio_id, asset.parent_task_id, payload.get("operationType"), payload.get("task_type")])
    if "extend" in text:
        return "extended"
    if "cover" in text:
        return "cover"
    if "vocal" in text:
        return "vocals"
    if "instrumental" in text:
        return "instrumental"
    if "midi" in text:
        return "midi"
    if "wav" in text:
        return "wav"
    return "generated"


def _best_asset_title(asset: AudioAsset) -> str:
    candidates = [asset.display_title, asset.title]
    payload = asset.metadata_json or {}
    for key in ("title", "songTitle", "name"):
        if payload.get(key):
            candidates.append(str(payload[key]))
    for value in candidates:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered.startswith("audio_") or lowered.startswith("task_"):
            continue
        if asset.audio_id and text == asset.audio_id:
            continue
        if asset.suno_task_id and text == asset.suno_task_id:
            continue
        return text
    if asset.song_id:
        return f"Song {asset.song_id}"
    if asset.audio_id:
        return f"Audio {asset.audio_id[:8]}"
    return f"Audio {asset.id}"


def _version_label_from_operation(operation: str, asset: AudioAsset) -> str:
    existing = (asset.version_label or "").strip()
    if existing:
        return existing
    mapping = {
        "generated": "Original",
        "extended": "Extend",
        "cover": "Cover Song",
        "vocals": "Add Vocals",
        "instrumental": "Add Instrumental",
        "midi": "MIDI",
        "wav": "WAV",
    }
    return mapping.get(operation, operation.title() if operation else "Version")


def _resolve_audio_file_from_storage(asset: AudioAsset) -> Path | None:
    storage_path = settings.audio_storage_path
    candidates: list[Path] = []

    def add_candidate(value: str | Path | None) -> None:
        if not value:
            return
        candidate = Path(str(value))
        candidates.append(candidate)
        if candidate.name:
            candidates.append(storage_path / candidate.name)

    add_candidate(asset.local_path)
    add_candidate(asset.filename)
    if asset.public_url:
        add_candidate(Path(str(asset.public_url).split("?", 1)[0]).name)
    if asset.source_url:
        add_candidate(Path(str(asset.source_url).split("?", 1)[0]).name)

    if storage_path.exists():
        for extension in settings.audio_allowed_extensions_list:
            candidates.extend(sorted(storage_path.glob(f"audio_{asset.id}_*{extension}")))
        candidates.extend(sorted(storage_path.glob(f"*{asset.id}_*.mp3")))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate if candidate.is_absolute() else candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _repair_single_audio_asset(asset: AudioAsset) -> tuple[bool, str]:
    path = _resolve_audio_file_from_storage(asset)
    if not path:
        return False, "local_file_missing"

    changed = False
    expected_public_url = f"{settings.suno_audio_public_route.rstrip('/')}/{path.name}"
    updates = {
        "status": "cached",
        "local_path": to_portable_path(path, storage_root=settings.audio_storage_path),
        "filename": path.name,
        "public_url": expected_public_url,
        "file_size_bytes": path.stat().st_size,
        "content_type": normalize_audio_content_type(asset.content_type, path),
    }
    duration = read_audio_duration_seconds(path)
    if duration:
        updates["duration_seconds"] = duration

    for field, value in updates.items():
        if getattr(asset, field) != value:
            setattr(asset, field, value)
            changed = True

    if asset.error_message and asset.status == "cached":
        asset.error_message = None
        changed = True

    return changed, "repaired" if changed else "ok"



@router.post("/maintenance/repair-audio-storage")
def repair_audio_storage(db: Session = Depends(get_db)) -> dict[str, Any]:
    # Umfassende Reparatur für Altbestände:
    # - entfernt Bild-URLs aus audio_assets
    # - normalisiert audio/mp3 -> audio/mpeg
    # - rekonstruiert AudioAssets aus suno_tasks.result_payload.response.sunoData
    # - dedupliziert je audio_id und bevorzugt lokal gecachte Dateien
    # - repariert local_path/public_url nach Projektumzug
    return repair_audio_library(db)


def _safe_count(db: Session, label: str, query: Any, warnings: list[str]) -> int:
    try:
        return int(query.count())
    except Exception as exc:
        warnings.append(f"{label} konnte nicht gezählt werden: {exc.__class__.__name__}")
        return 0


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db)) -> dict[str, Any]:
    warnings: list[str] = []
    storage_path = settings.audio_storage_path
    try:
        storage_path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        warnings.append(f"Audio-Storage-Verzeichnis konnte nicht vorbereitet werden: {exc.__class__.__name__}")

    counts = {
        "tasks": _safe_count(db, "Tasks", db.query(SunoTask), warnings),
        "songs": _safe_count(db, "Songs", db.query(Song), warnings),
        "audio_assets": _safe_count(db, "Audio-Assets", db.query(AudioAsset), warnings),
        "audio_assets_cached": _safe_count(db, "Gecachte Audio-Assets", db.query(AudioAsset).filter(AudioAsset.status == "cached"), warnings),
        "audio_assets_failed": _safe_count(db, "Fehlerhafte Audio-Assets", db.query(AudioAsset).filter(AudioAsset.status == "failed", AudioAsset.is_deleted.is_(False)), warnings),
        "projects": _safe_count(db, "Projekte", db.query(AudioProject), warnings),
        "personas": _safe_count(db, "Personas", db.query(Persona), warnings),
        "playlists": _safe_count(db, "Playlists", db.query(Playlist), warnings),
        "lyrics_drafts": _safe_count(db, "Songtext-Entwürfe", db.query(LyricDraft), warnings),
        "music_styles": _safe_count(db, "Musikstile", db.query(MusicStyle), warnings),
        "production_profiles": _safe_count(db, "Produktionsprofile", db.query(ProductionProfile), warnings),
        "users": _safe_count(db, "Benutzer", db.query(User), warnings),
        "active_users": _safe_count(db, "Aktive Benutzer", db.query(User).filter(User.is_active.is_(True)), warnings),
    }

    storage_files = []
    storage_bytes = 0
    try:
        if storage_path.exists() and storage_path.is_dir():
            for path in storage_path.rglob("*"):
                if path.is_file():
                    storage_files.append(path)
                    storage_bytes += path.stat().st_size
    except Exception as exc:
        warnings.append(f"Audio-Storage konnte nicht vollständig gelesen werden: {exc.__class__.__name__}")

    counts["storage_files"] = len(storage_files)
    counts["storage_bytes"] = storage_bytes

    if not settings.suno_api_key:
        warnings.append("SUNO_API_KEY fehlt in der .env.")
    if not settings.suno_audio_public_route.startswith("/"):
        warnings.append("SUNO_AUDIO_PUBLIC_ROUTE sollte mit / beginnen.")
    if settings.suno_audio_cache_mode != "off" and not storage_path.exists():
        warnings.append("Audio-Storage-Verzeichnis existiert nicht.")
    if settings.suno_audio_cache_mode != "off" and storage_path.exists() and not storage_path.is_dir():
        warnings.append("Audio-Storage-Pfad ist kein Verzeichnis.")

    try:
        database = {
            "engine": engine.url.drivername,
            "url_safe": settings.database_url if "@" not in settings.database_url else "configured",
        }
    except Exception as exc:
        database = {"error": f"Datenbankinfo nicht verfügbar: {exc.__class__.__name__}"}
        warnings.append(database["error"])

    return {
        "ok": len([warning for warning in warnings if "SUNO_API_KEY fehlt" not in warning]) == 0,
        "checked_at": utc_now_naive().isoformat(),
        "config": _safe_config(),
        "database": database,
        "counts": counts,
        "warnings": warnings,
    }


@router.get("/maintenance/database/status")
def database_maintenance_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Read-only Übersicht zur DB-Konsistenz. Führt keine Reparaturen aus."""
    return inspect_database_maintenance(db)


@router.post("/maintenance/database/run")
def database_maintenance_run(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sichere DB-Wartung mit Dry-Run/Backup.

    Standard ist dry_run=True. Ein echter Lauf benötigt confirm=True, damit
    Reparaturen nicht versehentlich aus dem Frontend ausgelöst werden.
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    confirm = bool(payload.get("confirm", False))
    if not dry_run and not confirm:
        raise HTTPException(status_code=400, detail="Echter DB-Wartungslauf benötigt confirm=true.")
    result = run_database_maintenance(
        db,
        dry_run=dry_run,
        backup=bool(payload.get("backup", True)),
        vacuum=bool(payload.get("vacuum", False)),
        materialize_limit=int(payload.get("materialize_limit") or 500),
    )
    result_payload = result.as_dict()
    changed_total = sum(int(action.get("count") or 0) for action in result_payload.get("actions", []))
    summary = result_payload.get("summary") or {}
    severity = "success" if result.ok and not dry_run else "info"
    if result.max_severity in {"critical", "high"}:
        severity = "error" if not dry_run else "warning"
    elif result.max_severity == "medium":
        severity = "warning" if not dry_run else "info"
    mode_label = "Dry-Run" if dry_run else "Reparatur"
    create_system_status_notification(
        db,
        event_type="database_maintenance_dry_run" if dry_run else "database_maintenance_completed",
        title=f"Datenbankwartung {mode_label}: {changed_total} Auffälligkeiten",
        message=(
            f"Integrität: {result.integrity}. "
            f"Max. Schweregrad: {result.max_severity}. "
            f"Backup: {result.backup_path or 'nicht erstellt'}."
        ),
        severity=severity,
        target_tab="system",
        target_payload={
            "target_tab": "system",
            "section": "database_maintenance",
            "dry_run": dry_run,
            "ok": result.ok,
            "integrity": result.integrity,
            "max_severity": result.max_severity,
            "summary": summary,
            "changed_total": changed_total,
            "backup_path": result.backup_path,
            "click_target": "system_database_maintenance",
        },
        commit=True,
    )
    return result_payload


@router.post("/maintenance/cache-external-covers")
async def cache_external_covers(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Lokalen Cache für externe Cover-Referenzen über die System-Wartung pflegen.

    Diese Route ist bewusst von /api/archive/covers/cache-missing getrennt:
    sie arbeitet mit Dry-Run als sicherem Standard, begrenztem Umfang und einem
    Wartungs-Resultatformat für die Systemseite. Nicht als Audio-Asset-Cache
    oder SRT-/Video-Nebenpfad zweckentfremden.
    """
    payload = payload or {}
    confirm = bool(payload.get("confirm", False))
    dry_run = bool(payload.get("dry_run", not confirm))
    if not dry_run and not confirm:
        raise HTTPException(status_code=400, detail="Echter Cover-Cache-Lauf benötigt confirm=true.")
    try:
        limit = int(payload.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(500, limit))
    result = await cache_external_cover_references(db, dry_run=dry_run, limit=limit)
    create_system_status_notification(
        db,
        event_type="external_cover_cache_dry_run" if dry_run else "external_cover_cache_completed",
        title=("Externe Cover geprüft" if dry_run else "Externe Cover lokal gesichert"),
        message=(
            f"Kandidaten: {int(result.get('candidate_urls') or 0)}, "
            f"Referenzen: {int(result.get('reference_count') or 0)}, "
            f"Downloads: {int(result.get('downloaded') or 0)}, "
            f"Fehler: {int(result.get('failed') or 0)}."
        ),
        severity="info" if dry_run or result.get("ok", True) else "warning",
        target_tab="system",
        target_payload={
            "target_tab": "system",
            "section": "cover_cache",
            "dry_run": dry_run,
            "limit": limit,
            "result": result,
            "click_target": "system_cover_cache",
        },
        commit=True,
    )
    return result


@router.get("/export")
def export_library(db: Session = Depends(get_db)) -> JSONResponse:
    data = {
        "exported_at": utc_now_naive().isoformat(),
        "app": settings.app_name,
        "version": "user-workflow-final-plus",
        "tasks": [_model_to_dict(row) for row in db.query(SunoTask).order_by(SunoTask.id.asc()).all()],
        "songs": [_model_to_dict(row) for row in db.query(Song).order_by(Song.id.asc()).all()],
        "audio_assets": [_model_to_dict(row) for row in db.query(AudioAsset).order_by(AudioAsset.id.asc()).all()],
        "projects": [_model_to_dict(row) for row in db.query(AudioProject).order_by(AudioProject.id.asc()).all()],
        "personas": [_model_to_dict(row) for row in db.query(Persona).order_by(Persona.id.asc()).all()],
        "playlists": [_model_to_dict(row) for row in db.query(Playlist).order_by(Playlist.id.asc()).all()],
        "playlist_items": [_model_to_dict(row) for row in db.query(PlaylistItem).order_by(PlaylistItem.id.asc()).all()],
        "lyric_drafts": [_model_to_dict(row) for row in db.query(LyricDraft).order_by(LyricDraft.id.asc()).all()],
        "music_styles": [_model_to_dict(row) for row in db.query(MusicStyle).order_by(MusicStyle.id.asc()).all()],
        "production_profiles": [_model_to_dict(row) for row in db.query(ProductionProfile).order_by(ProductionProfile.id.asc()).all()],
        "uploaded_files": [_model_to_dict(row) for row in db.query(UploadedFileRecord).order_by(UploadedFileRecord.id.asc()).all()],
    }
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": "attachment; filename=suno_fastapi_library_export.json"},
    )




@router.post("/maintenance/recover-stale-tasks")
def recover_stale_background_tasks(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload or {}
    raw_ids = payload.get("task_ids") or []
    task_ids: list[int] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0:
                task_ids.append(value)
    return recover_stale_tasks(
        db,
        stale_after_minutes=int(payload.get("stale_after_minutes") or settings.task_watchdog_stale_minutes),
        local_only=bool(payload.get("local_only", True)),
        dry_run=bool(payload.get("dry_run", True)),
        task_ids=task_ids or None,
    )


@router.post("/maintenance/cleanup-failed-audio")
def cleanup_failed_audio(db: Session = Depends(get_db)) -> dict[str, Any]:
    deleted_rows = 0
    deleted_files = 0
    failed_assets = db.query(AudioAsset).filter(AudioAsset.status == "failed").all()
    for asset in failed_assets:
        if asset.local_path:
            path = Path(asset.local_path)
            if path.exists() and path.is_file():
                path.unlink(missing_ok=True)
                deleted_files += 1
        db.delete(asset)
        deleted_rows += 1
    db.commit()
    return {"ok": True, "deleted_audio_rows": deleted_rows, "deleted_files": deleted_files}


@router.post("/maintenance/rebuild-projects")
def rebuild_projects(db: Session = Depends(get_db)) -> dict[str, Any]:
    created = 0
    updated = 0
    for asset in db.query(AudioAsset).order_by(AudioAsset.created_at.asc()).all():
        title = (asset.display_title or asset.title or "Unbenannt").strip() or "Unbenannt"
        base_title = (
            title.replace(" Extended Again", "")
            .replace(" Extended", "")
            .replace(" Cover Song", "")
            .replace(" Cover", "")
            .replace(" Add Vocals", "")
            .replace(" Add Instrumental", "")
            .replace(" Final", "")
            .strip()
            or title
        )
        project = db.query(AudioProject).filter(AudioProject.title == base_title).first()
        if not project:
            project = AudioProject(title=base_title, cover_image_url=asset.image_url)
            db.add(project)
            db.flush()
            created += 1
        if asset.project_id != project.id:
            asset.project_id = project.id
            updated += 1
        if not asset.display_title:
            asset.display_title = title
        if not project.cover_image_url and asset.image_url:
            project.cover_image_url = asset.image_url
    db.commit()
    return {"ok": True, "created_projects": created, "updated_audio_assets": updated}


@router.get("/export-zip")
def export_library_zip(db: Session = Depends(get_db)) -> StreamingResponse:
    export_payload = {
        "exported_at": utc_now_naive().isoformat(),
        "app": settings.app_name,
        "version": "operations-plus-backup",
        "config": _safe_config(),
        "tasks": [_model_to_dict(row) for row in db.query(SunoTask).order_by(SunoTask.id.asc()).all()],
        "songs": [_model_to_dict(row) for row in db.query(Song).order_by(Song.id.asc()).all()],
        "audio_assets": [_model_to_dict(row) for row in db.query(AudioAsset).order_by(AudioAsset.id.asc()).all()],
        "projects": [_model_to_dict(row) for row in db.query(AudioProject).order_by(AudioProject.id.asc()).all()],
        "personas": [_model_to_dict(row) for row in db.query(Persona).order_by(Persona.id.asc()).all()],
        "playlists": [_model_to_dict(row) for row in db.query(Playlist).order_by(Playlist.id.asc()).all()],
        "playlist_items": [_model_to_dict(row) for row in db.query(PlaylistItem).order_by(PlaylistItem.id.asc()).all()],
        "lyric_drafts": [_model_to_dict(row) for row in db.query(LyricDraft).order_by(LyricDraft.id.asc()).all()],
        "music_styles": [_model_to_dict(row) for row in db.query(MusicStyle).order_by(MusicStyle.id.asc()).all()],
        "production_profiles": [_model_to_dict(row) for row in db.query(ProductionProfile).order_by(ProductionProfile.id.asc()).all()],
        "uploaded_files": [_model_to_dict(row) for row in db.query(UploadedFileRecord).order_by(UploadedFileRecord.id.asc()).all()],
    }

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        import json
        zip_file.writestr("library_export.json", json.dumps(export_payload, ensure_ascii=False, indent=2, default=str))
        referenced_paths: set[Path] = set()
        for asset in db.query(AudioAsset).all():
            if not asset.local_path:
                continue
            path = Path(asset.local_path)
            if not path.exists() or not path.is_file():
                continue
            if path in referenced_paths:
                continue
            referenced_paths.add(path)
            title = _safe_filename(asset.display_title or asset.title, f"audio_{asset.id}")
            zip_file.write(path, arcname=f"audio/{asset.id}_{title}{path.suffix}")

    buffer.seek(0)
    filename = f"suno_fastapi_backup_{utc_now_naive().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/maintenance/fix-library-metadata")
def fix_library_metadata(db: Session = Depends(get_db)) -> dict[str, Any]:
    updated_assets = 0
    updated_projects = 0

    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.created_at.asc()).all():
        if is_bad_image_asset(asset):
            continue
        changed = False
        operation = _operation_from_asset(asset)
        title = _best_asset_title(asset)
        version_label = _version_label_from_operation(operation, asset)

        if not asset.operation_label or asset.operation_label != operation:
            asset.operation_label = operation
            changed = True
        if not asset.display_title or asset.display_title.startswith("audio_") or asset.display_title == asset.audio_id or asset.display_title == asset.suno_task_id:
            asset.display_title = title
            changed = True
        if not asset.version_label:
            asset.version_label = version_label
            changed = True

        if not asset.project_id:
            base_title = title
            for marker in (" Extended Again", " Extended", " Cover Song", " Cover", " Add Vocals", " Add Instrumental", " Final"):
                base_title = base_title.replace(marker, "")
            base_title = base_title.strip() or title
            project = db.query(AudioProject).filter(AudioProject.title == base_title).first()
            if not project:
                project = AudioProject(title=base_title, cover_image_url=asset.image_url)
                db.add(project)
                db.flush()
                updated_projects += 1
            asset.project_id = project.id
            changed = True
            if not project.cover_image_url and asset.image_url:
                project.cover_image_url = asset.image_url

        if changed:
            updated_assets += 1

    for project in db.query(AudioProject).all():
        assets = db.query(AudioAsset).filter(AudioAsset.project_id == project.id).order_by(AudioAsset.created_at.asc()).all()
        if not assets:
            continue
        if not project.cover_image_url:
            cover = next((asset.image_url for asset in assets if asset.image_url), None)
            if cover:
                project.cover_image_url = cover
                updated_projects += 1
        if project.final_audio_asset_id and not any(asset.id == project.final_audio_asset_id for asset in assets):
            project.final_audio_asset_id = None
            updated_projects += 1

    db.commit()
    return {"ok": True, "updated_audio_assets": updated_assets, "updated_projects": updated_projects}


@router.post("/maintenance/deduplicate-audio")
def deduplicate_audio(db: Session = Depends(get_db)) -> dict[str, Any]:
    deleted_rows = 0
    preserved_rows = 0
    seen: dict[str, AudioAsset] = {}

    assets = db.query(AudioAsset).order_by(AudioAsset.is_final.desc(), AudioAsset.is_favorite.desc(), AudioAsset.created_at.asc()).all()
    for asset in assets:
        key = asset.checksum_sha256 or asset.audio_id or asset.source_url
        if not key:
            preserved_rows += 1
            continue
        existing = seen.get(key)
        if not existing:
            seen[key] = asset
            preserved_rows += 1
            continue
        for item in db.query(PlaylistItem).filter(PlaylistItem.audio_asset_id == asset.id).all():
            item.audio_asset_id = existing.id
        if asset.is_final:
            existing.is_final = True
            if asset.project_id:
                existing.project_id = asset.project_id
        if asset.is_favorite:
            existing.is_favorite = True
        if not existing.image_url and asset.image_url:
            existing.image_url = asset.image_url
        path = Path(asset.local_path) if asset.local_path else None
        db.delete(asset)
        deleted_rows += 1
        if path and path.exists() and path.is_file():
            still_used = db.query(AudioAsset).filter(AudioAsset.local_path == str(path)).first()
            if not still_used:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
    db.commit()
    return {"ok": True, "preserved_audio_rows": preserved_rows, "deleted_duplicate_rows": deleted_rows}


@router.post("/maintenance/remove-orphan-audio-files")
def remove_orphan_audio_files(db: Session = Depends(get_db)) -> dict[str, Any]:
    storage_path = settings.audio_storage_path
    storage_path.mkdir(parents=True, exist_ok=True)
    referenced = {Path(asset.local_path).resolve() for asset in db.query(AudioAsset).all() if asset.local_path}
    deleted_files = 0
    deleted_bytes = 0
    for path in storage_path.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in referenced:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        deleted_files += 1
        deleted_bytes += size
    return {"ok": True, "deleted_files": deleted_files, "deleted_bytes": deleted_bytes}


@router.get("/maintenance/storage-check")
def storage_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    ok_files = 0
    total_bytes = 0
    for asset in db.query(AudioAsset).all():
        if not asset.local_path:
            continue
        path = Path(asset.local_path)
        if path.exists() and path.is_file():
            ok_files += 1
            total_bytes += path.stat().st_size
        else:
            missing.append({"id": asset.id, "title": asset.display_title or asset.title, "path": asset.local_path})
    return {"ok": True, "existing_files": ok_files, "missing_files": missing, "total_bytes": total_bytes}


@router.get("/enterprise-readiness")
def enterprise_readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, message: str, severity: str = "info") -> None:
        checks.append({"name": name, "ok": ok, "message": message, "severity": severity})

    add_check("API-Key", bool(settings.suno_api_key), "SUNO_API_KEY ist gesetzt." if settings.suno_api_key else "SUNO_API_KEY fehlt.", "critical")
    add_check("Datenbank", True, f"Datenbank erreichbar: {settings.database_url}")
    add_check("Audio-Storage", settings.audio_storage_path.exists(), f"Storage: {settings.audio_storage_path}", "warning")
    add_check("Security-Header", settings.security_headers_enabled, "Security-Header aktiv." if settings.security_headers_enabled else "Security-Header deaktiviert.", "warning")
    add_check("Trusted Hosts", settings.trusted_hosts_list != ["*"], "Trusted Hosts eingeschränkt." if settings.trusted_hosts_list != ["*"] else "Trusted Hosts erlaubt aktuell alle Hosts (*).", "warning")
    add_check("Enterprise Mode", settings.enterprise_mode, "Enterprise Mode aktiv." if settings.enterprise_mode else "Enterprise Mode nicht aktiv.", "info")
    add_check("JWT Secret", bool(settings.jwt_secret_key), "JWT_SECRET_KEY ist gesetzt." if settings.jwt_secret_key else "JWT_SECRET_KEY fehlt.", "critical")
    add_check("Registrierung", not settings.registration_enabled, "Registrierung ist deaktiviert." if not settings.registration_enabled else "Registrierung ist aktuell aktiviert und sollte nach dem Setup deaktiviert werden.", "warning")
    add_check("Auth Cookie Secure", settings.auth_cookie_secure or not settings.enterprise_mode, "Auth-Cookie Secure ist aktiv." if settings.auth_cookie_secure else "AUTH_COOKIE_SECURE sollte bei HTTPS/Produktivbetrieb true sein.", "warning")

    active_tasks = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).count()
    active_audio = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).count()
    deleted_items = (
        db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(True)).count()
        + db.query(Song).filter(Song.is_deleted.is_(True)).count()
        + db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(True)).count()
    )
    failed_audio = db.query(AudioAsset).filter(AudioAsset.status == "failed").count()

    readiness_score = round((sum(1 for check in checks if check["ok"]) / max(1, len(checks))) * 100)
    return {
        "ok": all(check["ok"] or check["severity"] != "critical" for check in checks),
        "readiness_score": readiness_score,
        "checks": checks,
        "metrics": {
            "active_tasks": active_tasks,
            "active_audio_assets": active_audio,
            "trash_items_estimate": deleted_items,
            "failed_audio_assets": failed_audio,
            "users": db.query(User).count(),
            "active_users": db.query(User).filter(User.is_active.is_(True)).count(),
        },
    }


@router.get("/activity")
def system_activity(limit: int = 100, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    rows = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return [_model_to_dict(row) for row in rows]


@router.post("/maintenance/cleanup-audit-log")
def cleanup_audit_log(days: int | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    from datetime import timedelta

    retention_days = max(1, int(days or settings.audit_log_retention_days))
    cutoff = utc_now_naive() - timedelta(days=retention_days)
    deleted = db.query(ActivityLog).filter(ActivityLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "retention_days": retention_days, "deleted_activity_rows": deleted}


@router.get("/backups")
def list_backups() -> dict[str, Any]:
    backup_path = settings.backup_storage_path
    backup_path.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(backup_path.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        items.append({
            "filename": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"ok": True, "backup_dir": str(backup_path), "items": items}


@router.get("/portable-backup/status")
def portable_backup_info(db: Session = Depends(get_db)) -> dict[str, Any]:
    return portable_backup_status(db)


@router.post("/maintenance/normalize-portable-paths")
def normalize_portable_storage_paths(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    result = normalize_portable_paths(db, dry_run=dry_run)
    stats = result.get("stats") or {}
    changed = sum(int(item.get("changed") or 0) for item in stats.values() if isinstance(item, dict))
    create_system_status_notification(
        db,
        event_type="portable_paths_dry_run" if dry_run else "portable_paths_normalized",
        title=("Portable Pfade geprüft" if dry_run else "Portable Pfade normalisiert"),
        message=f"Geänderte Pfade: {changed}.",
        severity="info" if dry_run else "success",
        target_tab="system",
        target_payload={
            "target_tab": "system",
            "section": "portable_backup",
            "dry_run": dry_run,
            "changed": changed,
            "stats": stats,
            "click_target": "system_portable_backup",
        },
        commit=True,
    )
    return result


@router.post("/portable-backup/export")
def create_portable_backup_endpoint(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> FileResponse:
    payload = payload or {}
    mode = str(payload.get("mode") or "full").strip().lower()
    scopes = payload.get("scopes") if isinstance(payload.get("scopes"), dict) else None
    if mode == "partial":
        backup_path = create_scoped_portable_backup(
            db,
            scopes=scopes,
            note=payload.get("note") if isinstance(payload.get("note"), str) else None,
        )
    else:
        backup_path = create_portable_backup(
            db,
            normalize_paths=bool(payload.get("normalize_paths", True)),
            note=payload.get("note") if isinstance(payload.get("note"), str) else None,
            scopes=scopes,
        )
    create_system_status_notification(
        db,
        event_type="portable_backup_export_completed",
        title="Portables Backup erstellt",
        message=f"Backup ist bereit: {backup_path.name}",
        severity="success",
        target_tab="system",
        target_payload={
            "target_tab": "system",
            "section": "portable_backup",
            "filename": backup_path.name,
            "path": str(backup_path),
            "click_target": "system_portable_backup",
        },
        commit=True,
    )
    return FileResponse(
        backup_path,
        media_type="application/zip",
        filename=backup_path.name,
        headers={"Content-Disposition": f'attachment; filename="{backup_path.name}"'},
    )


@router.post("/portable-backup/export/start")
def start_portable_backup_export_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return start_portable_backup_export_job(
        normalize_paths=bool(payload.get("normalize_paths", True)),
        note=payload.get("note") if isinstance(payload.get("note"), str) else None,
        mode=payload.get("mode") if isinstance(payload.get("mode"), str) else "full",
        scopes=payload.get("scopes") if isinstance(payload.get("scopes"), dict) else None,
    )


@router.get("/portable-backup/schedule")
def get_portable_backup_schedule_endpoint(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"ok": True, "schedule": get_portable_backup_schedule(db)}


@router.put("/portable-backup/schedule")
def update_portable_backup_schedule_endpoint(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"ok": True, "schedule": update_portable_backup_schedule(db, payload or {})}


@router.post("/portable-backup/schedule/run-now")
def run_portable_backup_schedule_now_endpoint(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return run_scheduled_portable_backup_once(db, force=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Automatisches Backup konnte nicht ausgeführt werden: {exc}") from exc


@router.get("/portable-backup/jobs/{job_id}")
def portable_backup_job_endpoint(job_id: str) -> dict[str, Any]:
    try:
        return get_portable_backup_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portable-Backup-Job wurde nicht gefunden.") from exc


@router.get("/portable-backup/export/{job_id}/download")
def download_portable_backup_job_endpoint(job_id: str) -> FileResponse:
    try:
        backup_path = get_portable_backup_download(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portable-Backup-Job wurde nicht gefunden.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        backup_path,
        media_type="application/zip",
        filename=backup_path.name,
        headers={"Content-Disposition": f'attachment; filename="{backup_path.name}"'},
    )


@router.post("/portable-backup/import")
async def import_portable_backup_endpoint(
    backup: UploadFile = File(...),
    confirm: bool = False,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=400, detail="Import abgebrochen: confirm=true ist erforderlich.")
    if not backup.filename or not backup.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Bitte ein Portable-Backup-ZIP auswählen.")
    settings.backup_storage_path.mkdir(parents=True, exist_ok=True)
    import_path = settings.backup_storage_path / f".uploaded-import-{utc_now_naive().strftime('%Y%m%d_%H%M%S')}-{_safe_filename(backup.filename, 'backup.zip')}"
    try:
        with import_path.open("wb") as handle:
            while True:
                chunk = await backup.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        result = import_portable_backup(import_path, create_pre_import_backup=True, db=db)
        create_system_status_notification(
            None,
            event_type="portable_backup_import_completed",
            title="Portables Backup importiert",
            message="Datenbank und lokale Dateien wurden aus einem portablen Backup übernommen.",
            severity="success",
            target_tab="system",
            target_payload={
                "target_tab": "system",
                "section": "portable_backup",
                "result": result,
                "click_target": "system_portable_backup",
            },
            commit=True,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Portable-Backup-Import fehlgeschlagen: {exc}") from exc

@router.post("/portable-backup/import/start")
async def start_portable_backup_import_endpoint(
    backup: UploadFile = File(...),
    confirm: bool = False,
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=400, detail="Import abgebrochen: confirm=true ist erforderlich.")
    if not backup.filename or not backup.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Bitte ein Portable-Backup-ZIP auswählen.")
    settings.backup_storage_path.mkdir(parents=True, exist_ok=True)
    import_path = settings.backup_storage_path / f".uploaded-import-{utc_now_naive().strftime('%Y%m%d_%H%M%S')}-{_safe_filename(backup.filename, 'backup.zip')}"
    try:
        with import_path.open("wb") as handle:
            while True:
                chunk = await backup.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        return start_portable_backup_import_job(import_path)
    except Exception as exc:  # noqa: BLE001
        try:
            import_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Portable-Backup-Import konnte nicht gestartet werden: {exc}") from exc
