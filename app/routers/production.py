from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models import ActivityLog, AudioAsset, AudioProject, AudioTranscript, LyricDraft, MusicStyle, Playlist, ProductionProfile, Song, StatusNotification, SunoTask
from app.services.audio_asset_repair_service import auto_group_audio_projects
from app.services.production_suite_service import (
    ROADMAP,
    analyze_asset_readiness,
    asset_events,
    build_video_plan,
    build_youtube_package,
    cockpit_payload,
    compact_asset_dict,
    duplicate_asset_version,
    get_asset_or_none,
    get_project_or_none,
    project_production_report,
    production_state,
    seed_style_presets,
    set_production_state,
)
from app.schemas import AudioAssetUpdate, AudioProjectCreate, AudioProjectUpdate, DuplicateAssetVersionRequest, ProductionProfileCreate, ProductionProfileUpdate, ProductionWorkflowUpdate
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/production", tags=["production"])


def _safe_export_filename(value: str | None, fallback: str = "suno_project") -> str:
    raw = (value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    return safe[:140].strip("._") or fallback


def _asset_export_dict(asset: AudioAsset) -> dict[str, Any]:
    return {
        **_asset_dict(asset),
        "prompt": asset.prompt,
        "lyrics": asset.lyrics,
        "style": asset.style,
        "model_name": asset.model_name,
        "source_image_url": asset.source_image_url,
    }


def _project_export_payload(project: AudioProject, db: Session) -> dict[str, Any]:
    assets = db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.created_at.asc(), AudioAsset.id.asc()).all()
    final_asset = next((asset for asset in assets if asset.id == project.final_audio_asset_id), None) or next((asset for asset in assets if asset.is_final), None)
    favorite_assets = [asset for asset in assets if asset.is_favorite]
    return {
        "exported_at": utc_now_naive().isoformat(),
        "export_type": "project",
        "version": "ux-workflow-final-fixed",
        "project": _project_dict(project, db),
        "summary": {
            "asset_count": len(assets),
            "playable_count": sum(1 for asset in assets if asset.public_url or asset.source_url or asset.filename or asset.audio_id),
            "favorite_count": len(favorite_assets),
            "final_audio_asset_id": final_asset.id if final_asset else None,
            "duration_seconds_total": sum(int(asset.duration_seconds or 0) for asset in assets),
        },
        "assets": [_asset_export_dict(asset) for asset in assets],
    }


def _project_export_text(payload: dict[str, Any]) -> str:
    project = payload["project"]
    lines = [
        f"Projekt: {project.get('title') or 'Unbenannt'}",
        f"Exportiert: {payload.get('exported_at')}",
        f"Varianten: {payload['summary'].get('asset_count', 0)}",
        f"Gesamtdauer: {payload['summary'].get('duration_seconds_total', 0)} Sekunden",
        "",
    ]
    for index, asset in enumerate(payload.get("assets", []), start=1):
        lines.extend([
            f"--- Variante {index}: {asset.get('display_title') or asset.get('title') or asset.get('audio_id') or asset.get('id')} ---",
            f"Status: {asset.get('status') or ''}",
            f"Audio-ID: {asset.get('audio_id') or ''}",
            f"Task-ID: {asset.get('suno_task_id') or ''}",
            f"Modell: {asset.get('model_name') or ''}",
            "",
            "STYLE:",
            asset.get("style") or "",
            "",
            "PROMPT / LYRICS:",
            asset.get("prompt") or asset.get("lyrics") or "",
            "",
        ])
    return "\n".join(lines).strip() + "\n"




def _safe_zip_part(value: Any, fallback: str = "item") -> str:
    raw = str(value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in raw)
    safe = "_".join(safe.split()).strip("._-")
    return safe[:96] or fallback


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolve_file_inside_roots(value: str | Path | None, roots: list[Path]) -> Path | None:
    if not value:
        return None
    raw = str(value).split("?", 1)[0].strip()
    if not raw:
        return None
    candidates: list[Path] = []
    candidate = Path(raw)
    candidates.append(candidate)
    for root in roots:
        if candidate.name:
            candidates.append(root / candidate.name)
        public_marker = f"/{root.name}/"
        if public_marker in raw:
            candidates.append(root / raw.rsplit(public_marker, 1)[-1])
    for item in candidates:
        try:
            resolved = item if item.is_absolute() else item.resolve()
        except Exception:
            continue
        if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        if any(_is_relative_to(resolved, root) for root in roots):
            return resolved
    return None


def _resolve_asset_audio_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    root = settings.audio_storage_path
    return _resolve_file_inside_roots(asset.local_path or asset.filename or asset.public_url or asset.source_url, [root])


def _resolve_asset_cover_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    root = settings.cover_storage_path
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    cover_cache = metadata.get("cover_cache") if isinstance(metadata.get("cover_cache"), dict) else {}
    candidates = [
        cover_cache.get("local_path"),
        cover_cache.get("filename"),
        cover_cache.get("public_url"),
        asset.cover_local_url,
        asset.image_url,
    ]
    for value in candidates:
        path = _resolve_file_inside_roots(value, [root])
        if path:
            return path
    return None


def _latest_asset_transcript(db: Session, asset_id: int) -> AudioTranscript | None:
    return (
        db.query(AudioTranscript)
        .filter(AudioTranscript.audio_asset_id == asset_id, AudioTranscript.status == "completed")
        .order_by(AudioTranscript.updated_at.desc(), AudioTranscript.id.desc())
        .first()
    )


def _write_text_if_present(zip_file: ZipFile, arcname: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    zip_file.writestr(arcname, text + "\n")
    return True


def _write_project_bundle_zip(zip_file: ZipFile, project: AudioProject, payload: dict[str, Any], db: Session) -> dict[str, Any]:
    import json

    assets = db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.created_at.asc(), AudioAsset.id.asc()).all()
    manifest: dict[str, Any] = {
        "project_id": project.id,
        "project_title": project.title,
        "exported_at": utc_now_naive().isoformat(),
        "included": [],
        "missing": [],
    }

    zip_file.writestr("project/project.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    zip_file.writestr("project/project.txt", _project_export_text(payload))

    for index, asset in enumerate(assets, start=1):
        title = asset.display_title or asset.title or asset.filename or f"audio_{asset.id}"
        folder = f"assets/{index:02d}_{_safe_zip_part(title, f'audio_{asset.id}')}_{asset.id}"
        asset_payload = _asset_export_dict(asset)
        zip_file.writestr(f"{folder}/metadata.json", json.dumps(asset_payload, ensure_ascii=False, indent=2, default=str))

        _write_text_if_present(zip_file, f"{folder}/lyrics.txt", asset.lyrics or asset.prompt)
        _write_text_if_present(zip_file, f"{folder}/prompt.txt", asset.prompt)
        _write_text_if_present(zip_file, f"{folder}/style.txt", asset.style)

        audio_path = _resolve_asset_audio_file(asset)
        if audio_path:
            arc = f"{folder}/audio/{_safe_zip_part(audio_path.stem, 'audio')}{audio_path.suffix.lower()}"
            zip_file.write(audio_path, arc)
            manifest["included"].append({"type": "audio", "asset_id": asset.id, "path": arc, "source": str(audio_path)})
        else:
            manifest["missing"].append({"type": "audio", "asset_id": asset.id, "reason": "Keine lokale Audiodatei gefunden."})

        cover_path = _resolve_asset_cover_file(asset)
        if cover_path:
            arc = f"{folder}/cover/{_safe_zip_part(cover_path.stem, 'cover')}{cover_path.suffix.lower()}"
            zip_file.write(cover_path, arc)
            manifest["included"].append({"type": "cover", "asset_id": asset.id, "path": arc, "source": str(cover_path)})
        elif asset.image_url:
            manifest["missing"].append({"type": "cover", "asset_id": asset.id, "reason": "Cover nur als Remote-URL vorhanden.", "url": asset.image_url})

        transcript = _latest_asset_transcript(db, asset.id)
        if transcript and transcript.srt_text:
            srt_name = _safe_zip_part(title, f"audio_{asset.id}") + ".srt"
            zip_file.writestr(f"{folder}/srt/{srt_name}", transcript.srt_text.strip() + "\n")
            manifest["included"].append({"type": "srt", "asset_id": asset.id, "path": f"{folder}/srt/{srt_name}"})
        else:
            manifest["missing"].append({"type": "srt", "asset_id": asset.id, "reason": "Keine erzeugte SRT vorhanden."})

    readme = [
        f"Suno Song Studio Projekt-Bundle: {project.title}",
        f"Exportiert: {manifest['exported_at']}",
        "",
        "Inhalt:",
        "- project/project.json und project/project.txt",
        "- assets/*/audio: lokal verfügbare Audiodateien",
        "- assets/*/cover: lokal verfügbare Cover",
        "- assets/*/srt: erzeugte Untertitel",
        "- assets/*/lyrics.txt, prompt.txt, style.txt und metadata.json",
        "",
        "Hinweis: Remote-only Inhalte werden im Manifest als fehlend mit URL/Grund protokolliert.",
    ]
    zip_file.writestr("README.txt", "\n".join(readme) + "\n")
    zip_file.writestr("00_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest

def _asset_dict(asset: AudioAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "task_local_id": asset.task_local_id,
        "song_id": asset.song_id,
        "suno_task_id": asset.suno_task_id,
        "audio_id": asset.audio_id,
        "title": asset.title,
        "display_title": asset.display_title,
        "operation_label": asset.operation_label,
        "parent_audio_id": asset.parent_audio_id,
        "parent_task_id": asset.parent_task_id,
        "version_label": asset.version_label,
        "project_id": asset.project_id,
        "is_favorite": bool(asset.is_favorite),
        "is_final": bool(asset.is_final),
        "image_url": asset.image_url,
        "source_url": asset.source_url,
        "public_url": asset.public_url,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "file_size_bytes": asset.file_size_bytes,
        "duration_seconds": asset.duration_seconds,
        "status": asset.status,
        "error_message": asset.error_message,
        "metadata_json": asset.metadata_json,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def _project_dict(project: AudioProject, db: Session) -> dict[str, Any]:
    assets = db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.created_at.asc()).all()
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "cover_image_url": project.cover_image_url or next((a.image_url for a in assets if a.image_url), None),
        "status": project.status,
        "is_favorite": bool(project.is_favorite),
        "final_audio_asset_id": project.final_audio_asset_id,
        "metadata_json": project.metadata_json,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "audio_assets": [_asset_dict(a) for a in assets],
    }




@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    audio_count = db.query(func.count(AudioAsset.id)).filter(AudioAsset.is_deleted.is_(False)).scalar() or 0
    project_count = db.query(func.count(AudioProject.id)).filter(AudioProject.is_deleted.is_(False)).scalar() or 0
    lyric_count = db.query(func.count(LyricDraft.id)).filter(LyricDraft.is_deleted.is_(False)).scalar() or 0
    playlist_count = db.query(func.count(Playlist.id)).filter(Playlist.is_deleted.is_(False)).scalar() or 0
    style_count = db.query(func.count(MusicStyle.id)).filter(MusicStyle.is_deleted.is_(False)).scalar() or 0
    pending_tasks = db.query(func.count(SunoTask.id)).filter(SunoTask.status.in_(["created", "pending", "running", "submitted"]), SunoTask.is_deleted.is_(False)).scalar() or 0
    unread_notifications = db.query(func.count(StatusNotification.id)).filter(StatusNotification.status != "done", StatusNotification.is_deleted.is_(False)).scalar() or 0
    latest_assets = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.updated_at.desc(), AudioAsset.id.desc()).limit(8).all()
    latest_projects = db.query(AudioProject).filter(AudioProject.is_deleted.is_(False)).order_by(AudioProject.updated_at.desc(), AudioProject.id.desc()).limit(6).all()
    return {
        "generated_at": utc_now_naive().isoformat(),
        "counts": {
            "audio_assets": audio_count,
            "projects": project_count,
            "lyrics": lyric_count,
            "playlists": playlist_count,
            "styles": style_count,
            "pending_tasks": pending_tasks,
            "unread_notifications": unread_notifications,
        },
        "workflow": [
            {"key": "idea", "label": "Idee", "description": "Songidee, Thema und Ziel festlegen."},
            {"key": "lyrics", "label": "Lyrics", "description": "Text im Studio vorbereiten oder verbessern."},
            {"key": "generate", "label": "Generieren", "description": "Suno-Auftrag starten und Varianten erzeugen."},
            {"key": "select", "label": "Auswählen", "description": "Beste Variante markieren und prüfen."},
            {"key": "edit", "label": "Bearbeiten", "description": "Extend, Cover, Vocals, Instrumental oder Persona nutzen."},
            {"key": "export", "label": "Export", "description": "Projekt als JSON/TXT/ZIP sichern."},
        ],
        "latest_assets": [_asset_dict(asset) for asset in latest_assets],
        "latest_projects": [_project_dict(project, db) for project in latest_projects],
    }




@router.get("/roadmap")
def production_roadmap():
    return {"generated_at": utc_now_naive().isoformat(), "items": ROADMAP}


@router.get("/cockpit")
def production_cockpit(limit: int = 40, db: Session = Depends(get_db)):
    return cockpit_payload(db, limit=limit)


@router.get("/audio/{asset_id}/workflow")
def read_audio_workflow(asset_id: int, db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    return {
        "asset": compact_asset_dict(db, asset),
        "production": production_state(asset),
        "readiness": analyze_asset_readiness(db, asset),
        "youtube_package": build_youtube_package(db, asset),
        "video_plan": build_video_plan(db, asset),
        "events": asset_events(db, asset),
    }


@router.patch("/audio/{asset_id}/workflow")
def update_audio_workflow(asset_id: int, payload: ProductionWorkflowUpdate, db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    state = set_production_state(db, asset, payload.model_dump(exclude_unset=True))
    return {
        "ok": True,
        "asset": compact_asset_dict(db, asset),
        "production": state,
        "readiness": analyze_asset_readiness(db, asset),
    }


@router.post("/audio/{asset_id}/duplicate-version")
def duplicate_audio_version(asset_id: int, payload: DuplicateAssetVersionRequest | None = None, db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    request = payload or DuplicateAssetVersionRequest()
    duplicate = duplicate_asset_version(db, asset, label=request.label, notes=request.notes)
    return {"ok": True, "source_audio_asset_id": asset.id, "audio_asset": compact_asset_dict(db, duplicate)}


@router.get("/audio/{asset_id}/youtube-package")
def read_youtube_package(asset_id: int, format: str = "json", db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    package = build_youtube_package(db, asset)
    if format.lower().strip() == "txt":
        filename = _safe_export_filename(package.get("title"), f"youtube_asset_{asset.id}")
        return StreamingResponse(
            BytesIO(str(package.get("text") or "").encode("utf-8")),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}_youtube.txt"},
        )
    return package


@router.get("/audio/{asset_id}/video-plan")
def read_video_plan(asset_id: int, db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    return build_video_plan(db, asset)


@router.get("/audio/{asset_id}/events")
def read_audio_events(asset_id: int, db: Session = Depends(get_db)):
    asset = get_asset_or_none(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    return {"asset_id": asset.id, "events": asset_events(db, asset)}


@router.post("/styles/seed-presets")
def seed_production_style_presets(db: Session = Depends(get_db)):
    return seed_style_presets(db)


@router.get("/projects/{project_id}/production-report")
def read_project_production_report(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_none(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
    return project_production_report(db, project)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(AudioProject).filter(AudioProject.is_deleted.is_(False)).order_by(AudioProject.updated_at.desc()).all()
    return [_project_dict(p, db) for p in projects]


@router.post("/projects")
def create_project(payload: AudioProjectCreate, db: Session = Depends(get_db)):
    project = AudioProject(**payload.model_dump(exclude_none=True))
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_dict(project, db)


@router.put("/projects/{project_id}")
def update_project(project_id: int, payload: AudioProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return _project_dict(project, db)




@router.get("/projects/{project_id}/export")
def export_project(project_id: int, format: str = "json", db: Session = Depends(get_db)):
    project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
    payload = _project_export_payload(project, db)
    filename = _safe_export_filename(project.title, f"project_{project.id}")
    normalized = format.lower().strip()
    if normalized == "txt":
        text = _project_export_text(payload)
        return StreamingResponse(
            BytesIO(text.encode("utf-8")),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}.txt"},
        )
    if normalized == "zip":
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
            _write_project_bundle_zip(zip_file, project, payload, db)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}.zip"},
        )
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f"attachment; filename={filename}.json"},
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
    old = {"id": project.id, "title": project.title, "status": project.status}
    project.is_deleted = True
    project.deleted_at = utc_now_naive()
    project.deleted_reason = "Projekt über Produktionsansicht gelöscht"
    db.add(ActivityLog(action="soft_delete", content_type="project", content_id=project.id, old_value=old, new_value={"is_deleted": True, "deleted_at": project.deleted_at.isoformat()}))
    db.commit()
    return {"ok": True, "deleted_project_id": project_id, "mode": "soft-delete"}


@router.post("/projects/{project_id}/assets/{asset_id}")
def add_asset_to_project(project_id: int, asset_id: int, db: Session = Depends(get_db)):
    project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    asset.project_id = project.id
    if not asset.display_title:
        asset.display_title = asset.title or project.title
    if not project.cover_image_url and asset.image_url:
        project.cover_image_url = asset.image_url
    db.commit()
    db.refresh(asset)
    return _project_dict(project, db)


@router.put("/audio/{asset_id}")
def update_audio_asset(asset_id: int, payload: AudioAssetUpdate, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_final") is True:
        # Nur eine finale Version pro Projekt markieren.
        project_id = data.get("project_id") or asset.project_id
        if project_id:
            for other in db.query(AudioAsset).filter(AudioAsset.project_id == project_id, AudioAsset.is_deleted.is_(False)).all():
                other.is_final = False
    for key, value in data.items():
        setattr(asset, key, value)
    if asset.is_final and asset.project_id:
        project = db.query(AudioProject).filter(AudioProject.id == asset.project_id).first()
        if project:
            project.final_audio_asset_id = asset.id
            if not project.cover_image_url and asset.image_url:
                project.cover_image_url = asset.image_url
    db.commit()
    db.refresh(asset)
    return _asset_dict(asset)


@router.post("/audio/{asset_id}/favorite")
def toggle_favorite(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    asset.is_favorite = not bool(asset.is_favorite)
    db.commit()
    db.refresh(asset)
    return _asset_dict(asset)


@router.post("/audio/{asset_id}/final")
def mark_final(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    if asset.project_id:
        for other in db.query(AudioAsset).filter(AudioAsset.project_id == asset.project_id, AudioAsset.is_deleted.is_(False)).all():
            other.is_final = False
    asset.is_final = True
    if asset.project_id:
        project = db.query(AudioProject).filter(AudioProject.id == asset.project_id).first()
        if project:
            project.final_audio_asset_id = asset.id
            if not project.cover_image_url and asset.image_url:
                project.cover_image_url = asset.image_url
    db.commit()
    db.refresh(asset)
    return _asset_dict(asset)


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return db.query(ProductionProfile).filter(ProductionProfile.is_deleted.is_(False)).order_by(ProductionProfile.is_favorite.desc(), ProductionProfile.updated_at.desc()).all()


@router.post("/profiles")
def create_profile(payload: ProductionProfileCreate, db: Session = Depends(get_db)):
    profile = ProductionProfile(**payload.model_dump(exclude_none=True))
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProductionProfileUpdate, db: Session = Depends(get_db)):
    profile = db.query(ProductionProfile).filter(ProductionProfile.id == profile_id, ProductionProfile.is_deleted.is_(False)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Produktionsprofil wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(ProductionProfile).filter(ProductionProfile.id == profile_id, ProductionProfile.is_deleted.is_(False)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Produktionsprofil wurde nicht gefunden.")
    old = {"id": profile.id, "name": profile.name}
    profile.is_deleted = True
    profile.deleted_at = utc_now_naive()
    profile.deleted_reason = "Produktionsprofil gelöscht"
    db.add(ActivityLog(action="soft_delete", content_type="production-profile", content_id=profile.id, old_value=old, new_value={"is_deleted": True, "deleted_at": profile.deleted_at.isoformat()}))
    db.commit()
    return {"ok": True, "deleted_profile_id": profile_id, "mode": "soft-delete"}


@router.post("/auto-group")
def auto_group_projects(db: Session = Depends(get_db)):
    updated = auto_group_audio_projects(db)
    db.commit()
    return {
        "ok": True,
        "updated_audio_assets": updated,
        "mode": "id_safe",
        "message": "Projektgruppen wurden ID-basiert geprüft. Titel wurden nicht als Identität verwendet.",
    }
