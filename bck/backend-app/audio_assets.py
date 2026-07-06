from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile
import hashlib
import importlib.util
import asyncio
import json
import mimetypes
import uuid
import shutil
import subprocess
import sys
import tempfile


from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.portable_path_service import to_portable_path
from app.database import SessionLocal, get_db
from app.models import ActivityLog, AudioAsset, AudioProject, AudioTranscript, Song, StatusNotification, SunoTask
from app.schemas import AudioAssetRead
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.audio_asset_repair_service import active_usable_audio_assets
from app.services.audio_ai_analysis_service import (
    AudioAiAnalysisOptions,
    create_audio_ai_status_task,
    fail_audio_ai_analysis_task,
    load_audio_ai_analysis_admin_settings,
    read_saved_audio_ai_analysis,
    resolve_audio_ai_export_path,
    run_audio_ai_analysis,
)
from app.services.library_ai_tagging_service import (
    create_library_ai_tagging_status_task,
    finish_library_ai_tagging_status_task,
    generate_library_ai_tags_for_asset,
    load_library_ai_tagging_settings,
    read_saved_library_ai_tags,
)
from app.services.background_task_runner import run_detached_process
from app.services.task_lifecycle_service import (
    append_task_debug_event,
    append_task_step_log,
    heartbeat_task,
    is_cancel_requested,
    mark_task_started,
    start_task_heartbeat,
)
from app.services.audio_cache_service import AudioCacheService, AudioCandidate
from app.services.srt_transcript_service import (
    generate_srt_for_audio_asset,
    get_saved_transcript,
    get_transcript_download_path,
    get_half_transcript_download_path,
    load_transcription_admin_settings,
    save_manual_srt_for_audio_asset,
    _create_srt_status_task,
)
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/audio-assets", tags=["audio-assets"])

# Aktiver SRT-Workflow des React-Frontends:
# LibraryPage/MiniPlayer sprechen diese AudioAsset-SRT-Routen über
# api.archive.getSrt/generateSrt/updateSrt an. Generische /api/srt/*-Routen
# bleiben Hilfsendpunkte und ersetzen diese Asset-gebundene Persistenz nicht.


class GenerateSrtRequest(BaseModel):
    lyrics_override: str | None = None
    force: bool = True
    language: str | None = None
    backend: str | None = None
    prefer_existing_vocal_stem: bool = True
    generate_vocal_stems_before_transcription: bool | None = None


class BulkGenerateSrtRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1, max_length=250)
    force: bool = True
    language: str | None = None
    backend: str | None = None
    prefer_existing_vocal_stem: bool = True
    generate_vocal_stems_before_transcription: bool | None = None


class BulkGenerateStemsRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1, max_length=250)


class AudioAiAnalysisRequest(BaseModel):
    profile: str = "standard"
    include_ai_report: bool = True
    force: bool = False


class LibraryAiTaggingRequest(BaseModel):
    force: bool = False


class BulkLibraryAiTaggingRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1, max_length=250)
    force: bool = False


class SrtSegmentRequest(BaseModel):
    start: float
    end: float
    text: str


class UpdateSrtRequest(BaseModel):
    srt_text: str | None = None
    segments: list[SrtSegmentRequest] | None = None


class DeleteAssetContentRequest(BaseModel):
    confirm: bool = False


class FavoriteAssetRequest(BaseModel):
    is_favorite: bool = True


class UpdateAssetLyricsRequest(BaseModel):
    lyrics: str = Field(default="", max_length=120000)
    prompt: str | None = Field(default=None, max_length=120000)


class ConvertAssetWavRequest(BaseModel):
    force: bool = False


def _safe_metadata(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_unlink(path_value: str | None, allowed_root: Path) -> bool:
    if not path_value:
        return False
    try:
        path = Path(path_value).expanduser().resolve()
        root = allowed_root.expanduser().resolve()
        if path != root and root not in path.parents:
            raise HTTPException(status_code=400, detail="Dateipfad liegt außerhalb des erlaubten Speicherbereichs.")
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Datei konnte nicht gelöscht werden: {exc}") from exc
    return False


def _path_from_public_url(public_url: str | None, public_route: str, storage_root: Path) -> Path | None:
    if not public_url:
        return None
    route = str(public_route or "").rstrip("/")
    value = str(public_url or "")
    if not route or not value.startswith(route + "/"):
        return None
    relative = value[len(route):].lstrip("/")
    if not relative or ".." in Path(relative).parts:
        return None
    return storage_root / relative


def _sanitize_upload_stem(value: Any, fallback: str = "audio") -> str:
    raw = str(value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in raw)
    safe = "_".join(safe.split()).strip("._- ")
    return safe[:80] or fallback


def _validate_upload_extension(filename: str | None, allowed_extensions: list[str], label: str) -> str:
    extension = Path(str(filename or "")).suffix.lower()
    if not extension or extension not in allowed_extensions:
        raise HTTPException(
            status_code=422,
            detail=f"Ungültige {label}-Dateiendung. Erlaubt: {', '.join(allowed_extensions)}",
        )
    return extension


def _public_url_for_storage_file(path: Path, storage_root: Path, public_route: str) -> str:
    relative = path.resolve().relative_to(storage_root.resolve()).as_posix()
    return f"{public_route.rstrip('/')}/{relative}"


def _write_upload_file(upload: UploadFile, target_path: Path, max_bytes: int) -> tuple[int, str]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    try:
                        target_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise HTTPException(status_code=413, detail="Datei ist größer als erlaubt.")
                digest.update(chunk)
                handle.write(chunk)
    finally:
        try:
            upload.file.close()
        except Exception:
            pass
    if total <= 0:
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=422, detail="Die hochgeladene Datei ist leer.")
    return total, digest.hexdigest()


def _write_optional_cover(upload: UploadFile | None, title: str, asset_token: str) -> dict[str, Any] | None:
    if not upload or not upload.filename:
        return None
    settings = get_settings()
    extension = _validate_upload_extension(upload.filename, settings.cover_allowed_extensions_list, "Cover")
    if upload.content_type and upload.content_type.lower() not in settings.cover_allowed_content_types_list:
        raise HTTPException(status_code=422, detail=f"Ungültiger Cover-Content-Type: {upload.content_type}")
    cover_root = settings.cover_storage_path
    filename = f"{_sanitize_upload_stem(title, 'cover')}_{asset_token}{extension}"
    target = (cover_root / filename).resolve()
    if not _is_relative_to(target, settings.cover_storage_path.resolve()):
        raise HTTPException(status_code=400, detail="Ungültiger Cover-Speicherpfad.")
    file_size, checksum = _write_upload_file(upload, target, settings.cover_max_download_bytes)
    public_url = _public_url_for_storage_file(target, settings.cover_storage_path, settings.suno_cover_public_route)
    return {
        "local_path": to_portable_path(target, storage_root=get_settings().cover_storage_path),
        "public_url": public_url,
        "filename": filename,
        "content_type": upload.content_type or mimetypes.guess_type(filename)[0] or "image/*",
        "file_size_bytes": file_size,
        "checksum_sha256": checksum,
    }


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
    direct = Path(raw)
    candidates.append(direct)
    for root in roots:
        candidates.append(root / direct.name)
        marker = f"/{root.name}/"
        if marker in raw:
            candidates.append(root / raw.rsplit(marker, 1)[-1])
    for item in candidates:
        try:
            resolved = item.expanduser().resolve()
        except Exception:
            continue
        if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        if any(_is_relative_to(resolved, root.expanduser().resolve()) for root in roots):
            return resolved
    return None


def _resolve_asset_audio_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    return _resolve_file_inside_roots(asset.local_path or asset.filename or asset.public_url, [settings.audio_storage_path])


def _is_external_http_url(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith(("http://", "https://"))


def _first_remote_audio_url_from_asset(asset: AudioAsset) -> str | None:
    metadata = _safe_metadata(asset.metadata_json)
    candidates: list[Any] = []

    preferred_keys = (
        "audioUrl",
        "audio_url",
        "downloadUrl",
        "download_url",
        "mp3Url",
        "mp3_url",
        "wavUrl",
        "wav_url",
        "sourceAudioUrl",
        "source_audio_url",
        "streamAudioUrl",
        "stream_audio_url",
        "sourceStreamAudioUrl",
        "source_stream_audio_url",
        "url",
    )
    for nested_key in ("candidate", "response_payload", "result_payload", "request_payload"):
        nested = metadata.get(nested_key)
        if isinstance(nested, dict):
            candidates.extend(nested.get(key) for key in preferred_keys)

    candidates.extend([
        metadata.get("audioUrl"),
        metadata.get("audio_url"),
        metadata.get("downloadUrl"),
        metadata.get("download_url"),
        metadata.get("sourceAudioUrl"),
        metadata.get("source_audio_url"),
        metadata.get("streamAudioUrl"),
        metadata.get("stream_audio_url"),
        metadata.get("source_url"),
        asset.source_audio_url,
        asset.source_url,
        asset.stream_audio_url,
    ])

    for value in candidates:
        if _is_external_http_url(value):
            return str(value).strip()
    return None


def _run_async_blocking(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _ensure_asset_audio_cached_for_wav(db: Session, asset: AudioAsset) -> Path | None:
    current = _resolve_asset_audio_file(asset)
    if current:
        return current
    source_url = _first_remote_audio_url_from_asset(asset)
    if not source_url:
        return None
    task = db.query(SunoTask).filter(SunoTask.id == asset.task_local_id).first() if asset.task_local_id else None
    song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
    candidate = AudioCandidate(
        source_url=source_url,
        audio_id=asset.audio_id,
        title=asset.display_title or asset.title or (song.title if song else None),
        image_url=asset.image_url,
        duration_seconds=asset.duration_seconds,
        metadata={"source": "wav_auto_cache", "asset_id": asset.id, "source_url": source_url},
    )
    cached_asset = _run_async_blocking(AudioCacheService(db).cache_candidate(candidate, task=task, song=song))
    db.refresh(asset)
    if cached_asset and cached_asset.id != asset.id and cached_asset.local_path and not asset.local_path:
        asset.local_path = cached_asset.local_path
        asset.public_url = cached_asset.public_url
        asset.filename = cached_asset.filename
        asset.content_type = cached_asset.content_type
        asset.file_size_bytes = cached_asset.file_size_bytes
        asset.checksum_sha256 = cached_asset.checksum_sha256
        asset.status = "cached"
        db.commit()
        db.refresh(asset)
    return _resolve_asset_audio_file(asset)


def _resolve_asset_cover_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    metadata = _safe_metadata(asset.metadata_json)
    cover_cache = metadata.get("cover_cache") if isinstance(metadata.get("cover_cache"), dict) else {}
    candidates = [
        cover_cache.get("local_path"),
        cover_cache.get("filename"),
        cover_cache.get("public_url"),
        asset.image_url,
    ]
    for candidate in candidates:
        path = _resolve_file_inside_roots(candidate, [settings.cover_storage_path])
        if path:
            return path
    return None




def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 512):
    with path.open("rb") as file_handle:
        file_handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file_handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _inline_streaming_file_response(path: Path, request: Request, *, media_type: str | None = None, filename: str | None = None) -> StreamingResponse:
    file_size = path.stat().st_size
    if file_size <= 0:
        raise HTTPException(status_code=404, detail="Datei ist leer.")

    resolved_media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    resolved_filename = filename or path.name
    range_header = request.headers.get("range")
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f'inline; filename="{resolved_filename}"',
    }

    if range_header:
        try:
            unit, requested_range = range_header.strip().split("=", 1)
            if unit.lower() != "bytes":
                raise ValueError("Unsupported range unit")
            start_text, end_text = requested_range.split("-", 1)
            if not start_text and end_text:
                suffix_length = int(end_text)
                if suffix_length <= 0:
                    raise ValueError("Invalid suffix range")
                start = max(file_size - suffix_length, 0)
                end = file_size - 1
            else:
                start = int(start_text) if start_text else 0
                end = int(end_text) if end_text else file_size - 1
            if start < 0 or end < start or start >= file_size:
                raise ValueError("Invalid range")
            end = min(end, file_size - 1)
        except ValueError:
            raise HTTPException(
                status_code=416,
                detail="Ungültiger Range-Header.",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        content_length = end - start + 1
        return StreamingResponse(
            _iter_file_range(path, start, end),
            status_code=206,
            media_type=resolved_media_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
            },
        )

    return StreamingResponse(
        _iter_file_range(path, 0, file_size - 1),
        media_type=resolved_media_type,
        headers={**base_headers, "Content-Length": str(file_size)},
    )


def _stem_storage_path() -> Path:
    return Path("storage/stems").resolve()


def _extract_bpm_from_asset(asset: AudioAsset) -> int | None:
    values: list[Any] = [asset.metadata_json, asset.style, asset.prompt, asset.lyrics, asset.display_title, asset.title]
    for value in values:
        if isinstance(value, dict):
            flat = json.dumps(value, ensure_ascii=False)
        else:
            flat = str(value or "")
        match = __import__("re").search(r"(?<!\d)([5-9]\d|1[0-9]{2}|2[0-2]\d)\s*(?:bpm|beats?\s*per\s*minute)?", flat, flags=__import__("re").IGNORECASE)
        if match:
            try:
                bpm = int(match.group(1))
                if 50 <= bpm <= 220:
                    return bpm
            except Exception:
                continue
    return None


def _asset_stem_metadata(asset: AudioAsset) -> dict[str, Any]:
    metadata = _safe_metadata(asset.metadata_json)
    stems = metadata.get("stems")
    return stems if isinstance(stems, dict) else {}


def _stem_file_entries(asset: AudioAsset) -> dict[str, dict[str, Any]]:
    stems = _asset_stem_metadata(asset)
    files = stems.get("files")
    return files if isinstance(files, dict) else {}


def _stem_download_payload(asset: AudioAsset) -> dict[str, Any]:
    stems = _asset_stem_metadata(asset)
    files = _stem_file_entries(asset)
    result_files: dict[str, Any] = {}
    for kind, entry in files.items():
        if not isinstance(entry, dict):
            continue
        path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
        if not path:
            continue
        result_files[kind] = {
            "kind": kind,
            "filename": entry.get("filename") or path.name,
            "size_bytes": path.stat().st_size,
            "content_type": entry.get("content_type") or mimetypes.guess_type(path.name)[0] or "audio/wav",
            "download_url": f"/api/audio-assets/{asset.id}/stems/{kind}/download",
            "stream_url": f"/api/audio-assets/{asset.id}/stems/{kind}/stream",
        }
    return {
        "audio_asset_id": asset.id,
        "exists": bool(result_files),
        "status": stems.get("status") or ("completed" if result_files else "missing"),
        "backend": stems.get("backend"),
        "bpm": stems.get("bpm"),
        "generated_at": stems.get("generated_at"),
        "error_message": stems.get("error_message"),
        "files": result_files,
        "zip_url": f"/api/audio-assets/{asset.id}/stems/download" if result_files else None,
    }


def _find_demucs_output(root: Path, stem_name: str, filename: str) -> tuple[Path | None, Path | None]:
    candidates = [
        root / "htdemucs" / stem_name,
        root / "htdemucs_ft" / stem_name,
    ]
    for candidate in root.glob(f"*/{stem_name}"):
        candidates.append(candidate)
    for folder in candidates:
        vocals = folder / "vocals.wav"
        instrumental = folder / "no_vocals.wav"
        if not instrumental.exists():
            instrumental = folder / "accompaniment.wav"
        if vocals.exists() and instrumental.exists():
            return vocals, instrumental
    # Fallback falls demucs einen anderen Ordnernamen nutzt
    for vocals in root.rglob("vocals.wav"):
        folder = vocals.parent
        instrumental = folder / "no_vocals.wav"
        if not instrumental.exists():
            instrumental = folder / "accompaniment.wav"
        if instrumental.exists():
            return vocals, instrumental
    return None, None


def _copy_stem_file(source: Path, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "local_path": to_portable_path(target, storage_root=get_settings().cover_storage_path),
        "filename": target.name,
        "content_type": "audio/wav",
        "file_size_bytes": target.stat().st_size,
        "checksum_sha256": digest.hexdigest(),
    }


def _asset_title(asset: AudioAsset, fallback: str = "AudioAsset") -> str:
    return str(asset.display_title or asset.title or asset.filename or fallback).strip() or fallback



def _wav_storage_path() -> Path:
    path = get_settings().audio_storage_path / "wav"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _asset_wav_metadata(asset: AudioAsset) -> dict[str, Any]:
    metadata = _safe_metadata(asset.metadata_json)
    wav_meta = metadata.get("wav_conversion") if isinstance(metadata.get("wav_conversion"), dict) else {}
    return wav_meta


def _resolve_asset_wav_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    wav_meta = _asset_wav_metadata(asset)
    candidates = [
        wav_meta.get("local_path"),
        wav_meta.get("filename"),
        wav_meta.get("public_url"),
    ]
    for candidate in candidates:
        path = _resolve_file_inside_roots(candidate, [settings.audio_storage_path, _wav_storage_path()])
        if path:
            return path
    return None


def _create_wav_status_task(db: Session, asset: AudioAsset, *, force: bool) -> SunoTask:
    title = _asset_title(asset, f"AudioAsset {asset.id}")
    task = SunoTask(
        task_id=None,
        task_type="convert_to_wav_local",
        status="RUNNING",
        request_payload={
            "audio_asset_id": asset.id,
            "title": title,
            "backend": "ffmpeg",
            "local_task": True,
            "force": force,
        },
        response_payload=None,
        result_payload=None,
        error_message=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    append_task_debug_event(
        db,
        task,
        event="wav_conversion_started",
        detail="WAV-Konvertierung wurde gestartet.",
        data={"audio_asset_id": asset.id, "title": title, "force": force, "backend": "ffmpeg"},
        commit=False,
    )
    append_task_step_log(
        db,
        task,
        phase="started",
        phase_label="WAV-Konvertierung gestartet",
        detail="Die lokale Audiodatei wird mit ffmpeg nach WAV konvertiert.",
        data={"audio_asset_id": asset.id},
        commit=False,
    )
    db.add(StatusNotification(
        event_type="wav_conversion_started",
        title=f"WAV-Konvertierung läuft: {title}",
        message="Die lokale Audiodatei wird mit ffmpeg nach WAV konvertiert.",
        severity="info",
        status="unread",
        task_local_id=task.id,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": "convert_to_wav_local", "status": "RUNNING"},
    ))
    db.commit()
    return task


def _finish_wav_status_task(db: Session, task: SunoTask | None, asset: AudioAsset, status: str, message: str, result_payload: dict[str, Any] | None = None) -> None:
    title = _asset_title(asset, f"AudioAsset {asset.id}")
    now = utc_now_naive()
    if task:
        task.status = status
        task.error_message = None if status == "SUCCESS" else message
        task.result_payload = result_payload or {"audio_asset_id": asset.id, "status": status, "message": message}
        append_task_debug_event(
            db,
            task,
            event="wav_conversion_finished",
            detail=message,
            level="info" if status == "SUCCESS" else "error",
            data={"audio_asset_id": asset.id, "status": status, "result": result_payload or {}},
            commit=False,
        )
        append_task_step_log(
            db,
            task,
            phase="completed" if status == "SUCCESS" else "failed",
            phase_label="WAV-Konvertierung abgeschlossen" if status == "SUCCESS" else "WAV-Konvertierung fehlgeschlagen",
            detail=message,
            data={"audio_asset_id": asset.id, "status": status},
            commit=False,
        )
        db.add(task)
        running_rows = (
            db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == "wav_conversion_started",
                StatusNotification.status != "done",
                StatusNotification.is_deleted.is_(False),
            )
            .all()
        )
        for row in running_rows:
            row.status = "done"
            row.completed_at = now
            row.message = f"Abgeschlossen: {message}"
            db.add(row)
    db.add(StatusNotification(
        event_type="wav_conversion_completed" if status == "SUCCESS" else "wav_conversion_failed",
        title=f"WAV-Konvertierung {'fertig' if status == 'SUCCESS' else 'fehlgeschlagen'}: {title}",
        message=message,
        severity="success" if status == "SUCCESS" else "error",
        status="unread",
        task_local_id=task.id if task else None,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id if task else None, "task_type": "convert_to_wav_local", "status": status},
        completed_at=now,
    ))
    db.commit()


def _wav_payload(asset: AudioAsset, wav_path: Path, *, task: SunoTask | None = None, created: bool = False, already_wav: bool = False) -> dict[str, Any]:
    settings = get_settings()
    public_url = _public_url_for_storage_file(wav_path, settings.audio_storage_path, settings.suno_audio_public_route)
    stat = wav_path.stat()
    return {
        "ok": True,
        "audio_asset_id": asset.id,
        "title": _asset_title(asset, f"AudioAsset {asset.id}"),
        "created": created,
        "already_wav": already_wav,
        "status": "completed",
        "backend": "ffmpeg" if not already_wav else "source_wav",
        "filename": wav_path.name,
        "local_path": to_portable_path(wav_path, storage_root=settings.audio_storage_path),
        "public_url": public_url,
        "download_url": f"/api/audio-assets/{asset.id}/wav/download",
        "content_type": "audio/wav",
        "file_size_bytes": stat.st_size,
        "task_local_id": task.id if task else None,
    }


def convert_asset_to_wav(db: Session, audio_asset_id: int, *, force: bool = False) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    existing = _resolve_asset_wav_file(asset)
    if existing and not force:
        return _wav_payload(asset, existing, created=False, already_wav=existing.suffix.lower() == ".wav")

    source_path = _ensure_asset_audio_cached_for_wav(db, asset)
    if not source_path:
        raise HTTPException(status_code=422, detail="Keine lokale Audiodatei oder extern nachladbare Audio-URL für WAV-Konvertierung gefunden.")
    if source_path.suffix.lower() == ".wav":
        metadata = _safe_metadata(asset.metadata_json)
        payload = _wav_payload(asset, source_path, created=False, already_wav=True)
        metadata["wav_conversion"] = {
            **payload,
            "source_audio_path": str(source_path),
            "updated_at": utc_now_naive().isoformat(),
        }
        asset.metadata_json = metadata
        if asset.song_id:
            song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
            if song:
                song.wav_url = payload["public_url"]
                song_metadata = _safe_metadata(song.metadata_json)
                song_metadata["wav_conversion"] = metadata["wav_conversion"]
                song.metadata_json = song_metadata
        db.commit()
        return payload

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="ffmpeg ist auf dem Server nicht verfügbar.")

    wav_task: SunoTask | None = None
    try:
        wav_task = _create_wav_status_task(db, asset, force=force)
        safe_title = _safe_zip_part(asset.display_title or asset.title or source_path.stem or f"audio_{asset.id}", f"audio_{asset.id}")
        target_dir = _wav_storage_path() / str(asset.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = (target_dir / f"{safe_title}_asset_{asset.id}.wav").resolve()
        if not _is_relative_to(target_path, get_settings().audio_storage_path.resolve()):
            raise HTTPException(status_code=400, detail="Ungültiger WAV-Speicherpfad.")

        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force or target_path.exists() else "-n",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(target_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 20)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ffmpeg-Konvertierung fehlgeschlagen.").strip()[-1200:]
            raise RuntimeError(detail)
        if not target_path.exists() or target_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg hat keine gültige WAV-Datei erzeugt.")

        payload = _wav_payload(asset, target_path, task=wav_task, created=True)
        metadata = _safe_metadata(asset.metadata_json)
        metadata["wav_conversion"] = {
            **payload,
            "source_audio_path": str(source_path),
            "source_filename": source_path.name,
            "converted_at": utc_now_naive().isoformat(),
            "command": "ffmpeg pcm_s16le 44.1kHz stereo",
        }
        asset.metadata_json = metadata
        if asset.song_id:
            song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
            if song:
                song.wav_url = payload["public_url"]
                song_metadata = _safe_metadata(song.metadata_json)
                song_metadata["wav_conversion"] = metadata["wav_conversion"]
                song.metadata_json = song_metadata
        db.add(ActivityLog(
            action="convert_to_wav",
            content_type="audio_asset",
            content_id=asset.id,
            old_value=None,
            new_value={"filename": payload["filename"], "file_size_bytes": payload["file_size_bytes"], "task_local_id": payload.get("task_local_id")},
            metadata_json={"source_path": str(source_path), "target_path": str(target_path)},
        ))
        db.commit()
        db.refresh(asset)
        _finish_wav_status_task(db, wav_task, asset, "SUCCESS", "WAV-Datei wurde lokal erzeugt und gespeichert.", payload)
        return payload
    except HTTPException as exc:
        if wav_task:
            _finish_wav_status_task(db, wav_task, asset, "FAILED", str(exc.detail))
        raise
    except Exception as exc:
        if wav_task:
            _finish_wav_status_task(db, wav_task, asset, "FAILED", str(exc))
        raise HTTPException(status_code=500, detail=f"WAV-Konvertierung fehlgeschlagen: {exc}") from exc


def _create_stem_status_task(db: Session, asset: AudioAsset) -> SunoTask:
    title = _asset_title(asset, f"AudioAsset {asset.id}")
    task = SunoTask(
        task_id=None,
        task_type="generate_stems",
        status="RUNNING",
        request_payload={
            "audio_asset_id": asset.id,
            "title": title,
            "backend": "demucs",
            "local_task": True,
        },
        response_payload=None,
        result_payload=None,
        error_message=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    append_task_debug_event(
        db,
        task,
        event="stem_generation_started",
        detail="Stem-Erzeugung wurde gestartet.",
        data={"audio_asset_id": asset.id, "title": title, "backend": "demucs"},
        commit=False,
    )
    append_task_step_log(
        db,
        task,
        phase="started",
        phase_label="Stem-Erzeugung gestartet",
        detail="Vocals und Instrumental werden lokal mit Demucs erzeugt.",
        data={"audio_asset_id": asset.id},
        commit=False,
    )
    db.add(StatusNotification(
        event_type="stem_generation_started",
        title=f"Stem-Erzeugung läuft: {title}",
        message="Vocals und Instrumental werden lokal mit Demucs erzeugt.",
        severity="info",
        status="unread",
        task_local_id=task.id,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": "generate_stems", "status": "RUNNING"},
    ))
    db.commit()
    return task


def _finish_stem_status_task(db: Session, task: SunoTask | None, asset: AudioAsset, status: str, message: str, result_payload: dict[str, Any] | None = None) -> None:
    title = _asset_title(asset, f"AudioAsset {asset.id}")
    now = utc_now_naive()
    if task:
        task.status = status
        task.error_message = None if status == "SUCCESS" else message
        task.result_payload = result_payload or {"audio_asset_id": asset.id, "status": status, "message": message}
        append_task_debug_event(
            db,
            task,
            event="stem_generation_finished",
            detail=message,
            level="info" if status == "SUCCESS" else "error",
            data={"audio_asset_id": asset.id, "status": status, "result": result_payload or {}},
            commit=False,
        )
        append_task_step_log(
            db,
            task,
            phase="completed" if status == "SUCCESS" else "failed",
            phase_label="Stem-Erzeugung abgeschlossen" if status == "SUCCESS" else "Stem-Erzeugung fehlgeschlagen",
            detail=message,
            data={"audio_asset_id": asset.id, "status": status},
            commit=False,
        )
        db.add(task)
        running_rows = (
            db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == "stem_generation_started",
                StatusNotification.status != "done",
                StatusNotification.is_deleted.is_(False),
            )
            .all()
        )
        for row in running_rows:
            row.status = "done"
            row.completed_at = now
            row.message = f"Abgeschlossen: {message}"
            db.add(row)
    db.add(StatusNotification(
        event_type="stem_generation_completed" if status == "SUCCESS" else "stem_generation_failed",
        title=f"Stem-Erzeugung {'fertig' if status == 'SUCCESS' else 'fehlgeschlagen'}: {title}",
        message=message,
        severity="success" if status == "SUCCESS" else "error",
        status="unread",
        task_local_id=task.id if task else None,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id if task else None, "task_type": "generate_stems", "status": status},
        completed_at=now,
    ))
    db.commit()


def _build_stems_zip(asset: AudioAsset) -> tuple[bytes, str]:
    files = _stem_file_entries(asset)
    title = asset.display_title or asset.title or f"audio_{asset.id}"
    safe_title = _safe_zip_part(title, f"audio_{asset.id}")
    bpm = _asset_stem_metadata(asset).get("bpm") or _extract_bpm_from_asset(asset) or "unknown"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        manifest = {"audio_asset_id": asset.id, "title": title, "bpm": bpm, "included": []}
        for kind in ("vocals", "instrumental"):
            entry = files.get(kind)
            if not isinstance(entry, dict):
                continue
            path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
            if not path:
                continue
            arc = f"stems/{path.name}"
            zip_file.write(path, arc)
            manifest["included"].append({"type": kind, "path": arc, "size_bytes": path.stat().st_size})
        zip_file.writestr("00_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        zip_file.writestr("README.txt", f"Stem-Paket für {title}\nAudioAsset-ID: {asset.id}\nBPM: {bpm}\n")
    buffer.seek(0)
    return buffer.getvalue(), f"{safe_title}_{bpm}bpm_stems_asset_{asset.id}.zip"


def generate_stems_for_asset(db: Session, audio_asset_id: int, status_task: SunoTask | None = None) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    stem_task: SunoTask | None = None
    try:
        audio_path = _resolve_asset_audio_file(asset)
        if not audio_path:
            raise HTTPException(status_code=422, detail="Keine lokale Audiodatei für Stem-Erzeugung gefunden.")
        if importlib.util.find_spec("demucs") is None:
            raise HTTPException(status_code=422, detail="Demucs ist nicht im FastAPI-Python-Environment installiert. Installiere es z. B. mit: pip install demucs")

        stem_task = status_task or _create_stem_status_task(db, asset)
        bpm = _extract_bpm_from_asset(asset)
        bpm_part = f"{bpm}bpm" if bpm else "unknownbpm"
        safe_title = _safe_zip_part(asset.display_title or asset.title or audio_path.stem or f"audio_{asset.id}", f"audio_{asset.id}")
        target_dir = _stem_storage_path() / str(asset.id)
        target_dir.mkdir(parents=True, exist_ok=True)

        metadata = _safe_metadata(asset.metadata_json)
        stems_meta = metadata.get("stems") if isinstance(metadata.get("stems"), dict) else {}
        stems_meta.update({
            "status": "running",
            "backend": "demucs",
            "started_at": utc_now_naive().isoformat(),
            "bpm": bpm,
            "task_local_id": stem_task.id,
        })
        metadata["stems"] = stems_meta
        asset.metadata_json = metadata
        db.commit()

        with tempfile.TemporaryDirectory(prefix=f"songstudio_stems_{asset.id}_") as tmp:
            out_root = Path(tmp).resolve()
            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "vocals",
                "-n",
                "htdemucs",
                "--out",
                str(out_root),
                str(audio_path),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "Demucs fehlgeschlagen.").strip()[-1200:]
                raise RuntimeError(detail)
            vocals_src, instrumental_src = _find_demucs_output(out_root, audio_path.stem, audio_path.name)
            if not vocals_src or not instrumental_src:
                raise RuntimeError("Demucs hat keine vocals.wav und no_vocals.wav erzeugt.")
            vocals_info = _copy_stem_file(vocals_src, target_dir / f"{safe_title}_{bpm_part}_vocals.wav")
            instrumental_info = _copy_stem_file(instrumental_src, target_dir / f"{safe_title}_{bpm_part}_instrumental.wav")

        metadata = _safe_metadata(asset.metadata_json)
        metadata["stems"] = {
            "status": "completed",
            "backend": "demucs",
            "mode": "two_stems_vocals",
            "bpm": bpm,
            "generated_at": utc_now_naive().isoformat(),
            "source_audio_path": str(audio_path),
            "task_local_id": stem_task.id,
            "files": {
                "vocals": vocals_info,
                "instrumental": instrumental_info,
            },
        }
        asset.metadata_json = metadata
        db.commit()
        db.refresh(asset)
        result = _stem_download_payload(asset)
        _finish_stem_status_task(db, stem_task, asset, "SUCCESS", "Stem-Dateien wurden erzeugt und gespeichert.", result)
        return result
    except HTTPException as exc:
        metadata = _safe_metadata(asset.metadata_json) if asset else {}
        if asset:
            stems_meta = metadata.get("stems") if isinstance(metadata.get("stems"), dict) else {}
            stems_meta.update({"status": "failed", "error_message": str(exc.detail), "updated_at": utc_now_naive().isoformat(), "task_local_id": stem_task.id if stem_task else None})
            metadata["stems"] = stems_meta
            asset.metadata_json = metadata
            db.commit()
            _finish_stem_status_task(db, stem_task, asset, "FAILED", str(exc.detail))
        raise
    except Exception as exc:
        if asset:
            metadata = _safe_metadata(asset.metadata_json)
            stems_meta = metadata.get("stems") if isinstance(metadata.get("stems"), dict) else {}
            stems_meta.update({"status": "failed", "error_message": str(exc), "updated_at": utc_now_naive().isoformat(), "task_local_id": stem_task.id if stem_task else None})
            metadata["stems"] = stems_meta
            asset.metadata_json = metadata
            db.commit()
            _finish_stem_status_task(db, stem_task, asset, "FAILED", str(exc))
        raise HTTPException(status_code=500, detail=f"Stem-Erzeugung fehlgeschlagen: {exc}") from exc

def _latest_completed_transcript(db: Session, asset_id: int) -> AudioTranscript | None:
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


def _asset_metadata_export(asset: AudioAsset, transcript: AudioTranscript | None = None) -> dict[str, Any]:
    return {
        "exported_at": utc_now_naive().isoformat(),
        "export_type": "single_audio_asset",
        "audio_asset": {
            "id": asset.id,
            "song_id": asset.song_id,
            "project_id": asset.project_id,
            "task_local_id": asset.task_local_id,
            "suno_task_id": asset.suno_task_id,
            "audio_id": asset.audio_id,
            "title": asset.title,
            "display_title": asset.display_title,
            "operation_label": asset.operation_label,
            "version_label": asset.version_label,
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
            "model_name": asset.model_name,
            "style": asset.style,
            "prompt": asset.prompt,
            "lyrics": asset.lyrics,
            "metadata_json": asset.metadata_json,
            "waveform_json": asset.waveform_json,
            "structure_segments_json": asset.structure_segments_json,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        },
        "transcript": {
            "id": transcript.id,
            "backend": transcript.backend,
            "language": transcript.language,
            "mode": transcript.mode,
            "match_mode": transcript.match_mode,
            "status": transcript.status,
            "generated_at": transcript.generated_at.isoformat() if transcript and transcript.generated_at else None,
            "updated_at": transcript.updated_at.isoformat() if transcript and transcript.updated_at else None,
        } if transcript else None,
    }


BUNDLE_CONTENT_TYPES = {
    "metadata",
    "lyrics",
    "prompt",
    "style",
    "timestamped_lyrics",
    "waveform",
    "structure",
    "audio",
    "cover",
    "stems",
    "srt",
}


def _parse_bundle_include(value: str | None) -> set[str] | None:
    if not value:
        return None
    parts = {str(item).strip().lower() for item in value.replace(";", ",").split(",") if str(item).strip()}
    normalized: set[str] = set()
    aliases = {
        "all": "all",
        "meta": "metadata",
        "metadaten": "metadata",
        "text": "lyrics",
        "songtext": "lyrics",
        "lyrics": "lyrics",
        "timestamped": "timestamped_lyrics",
        "timestampedlyrics": "timestamped_lyrics",
        "timestamped_lyrics": "timestamped_lyrics",
        "songstruktur": "structure",
        "structure_segments": "structure",
        "structure_segments_json": "structure",
        "stem": "stems",
        "vocals": "stems",
        "instrumental": "stems",
        "untertitel": "srt",
    }
    for part in parts:
        mapped = aliases.get(part, part)
        if mapped == "all":
            return None
        if mapped in BUNDLE_CONTENT_TYPES:
            normalized.add(mapped)
    return normalized or None


def _build_audio_asset_bundle(db: Session, asset: AudioAsset, include: set[str] | None = None) -> tuple[bytes, str]:
    def wants(kind: str) -> bool:
        return include is None or kind in include

    transcript = _latest_completed_transcript(db, asset.id)
    title = asset.display_title or asset.title or asset.filename or asset.audio_id or f"audio_{asset.id}"
    safe_title = _safe_zip_part(title, f"audio_{asset.id}")
    manifest: dict[str, Any] = {
        "audio_asset_id": asset.id,
        "title": title,
        "exported_at": utc_now_naive().isoformat(),
        "scope": "single_audio_asset",
        "requested_content": sorted(include) if include else "all",
        "included": [],
        "missing": [],
        "skipped": [],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        zip_file.writestr("README.txt", "\n".join([
            f"Suno Song Studio Audio-Paket: {title}",
            f"AudioAsset-ID: {asset.id}",
            f"Exportiert: {manifest['exported_at']}",
            "",
            "Dieses ZIP enthält die ausgewählten lokal verfügbaren Inhalte dieser einen Song-Variante.",
            "Fehlende, abgewählte oder nur remote verfügbare Inhalte stehen im Manifest.",
            "",
        ]))

        if wants("metadata"):
            zip_file.writestr("metadata.json", json.dumps(_asset_metadata_export(asset, transcript), ensure_ascii=False, indent=2, default=str))
            manifest["included"].append({"type": "metadata", "path": "metadata.json"})
        else:
            manifest["skipped"].append({"type": "metadata"})

        if wants("lyrics"):
            if _write_text_if_present(zip_file, "lyrics.txt", asset.lyrics or asset.prompt):
                manifest["included"].append({"type": "lyrics", "path": "lyrics.txt"})
            else:
                manifest["missing"].append({"type": "lyrics", "reason": "Kein Songtext/Prompt vorhanden."})
        else:
            manifest["skipped"].append({"type": "lyrics"})

        if wants("prompt"):
            if _write_text_if_present(zip_file, "prompt.txt", asset.prompt):
                manifest["included"].append({"type": "prompt", "path": "prompt.txt"})
            else:
                manifest["missing"].append({"type": "prompt", "reason": "Kein Prompt vorhanden."})
        else:
            manifest["skipped"].append({"type": "prompt"})

        if wants("style"):
            if _write_text_if_present(zip_file, "style.txt", asset.style):
                manifest["included"].append({"type": "style", "path": "style.txt"})
            else:
                manifest["missing"].append({"type": "style", "reason": "Kein Style vorhanden."})
        else:
            manifest["skipped"].append({"type": "style"})

        metadata = _safe_metadata(asset.metadata_json)
        timestamped = metadata.get("timestamped_lyrics") or metadata.get("timestampedLyrics")
        if wants("timestamped_lyrics"):
            if timestamped:
                zip_file.writestr("timestamped_lyrics.json", json.dumps(timestamped, ensure_ascii=False, indent=2, default=str))
                manifest["included"].append({"type": "timestamped_lyrics", "path": "timestamped_lyrics.json"})
            else:
                manifest["missing"].append({"type": "timestamped_lyrics", "reason": "Keine Timestamped Lyrics vorhanden."})
        else:
            manifest["skipped"].append({"type": "timestamped_lyrics"})

        if wants("waveform"):
            if asset.waveform_json:
                zip_file.writestr("waveform.json", json.dumps(asset.waveform_json, ensure_ascii=False, indent=2, default=str))
                manifest["included"].append({"type": "waveform", "path": "waveform.json"})
            else:
                manifest["missing"].append({"type": "waveform", "reason": "Keine Waveformdaten vorhanden."})
        else:
            manifest["skipped"].append({"type": "waveform"})

        if wants("structure"):
            if asset.structure_segments_json:
                zip_file.writestr("structure_segments.json", json.dumps(asset.structure_segments_json, ensure_ascii=False, indent=2, default=str))
                manifest["included"].append({"type": "structure", "path": "structure_segments.json"})
            else:
                manifest["missing"].append({"type": "structure", "reason": "Keine Struktursegmente vorhanden."})
        else:
            manifest["skipped"].append({"type": "structure"})

        if wants("audio"):
            audio_path = _resolve_asset_audio_file(asset)
            if audio_path:
                arcname = f"audio/{_safe_zip_part(audio_path.stem, 'audio')}{audio_path.suffix.lower()}"
                zip_file.write(audio_path, arcname)
                manifest["included"].append({"type": "audio", "path": arcname, "source": str(audio_path)})
            else:
                manifest["missing"].append({"type": "audio", "reason": "Keine lokale Audiodatei gefunden.", "remote_url": asset.source_url})
        else:
            manifest["skipped"].append({"type": "audio"})

        if wants("wav"):
            wav_path = _resolve_asset_wav_file(asset)
            if wav_path:
                arcname = f"audio/{_safe_zip_part(wav_path.stem, 'audio_wav')}.wav"
                zip_file.write(wav_path, arcname)
                manifest["included"].append({"type": "wav", "path": arcname, "source": str(wav_path)})
            else:
                manifest["missing"].append({"type": "wav", "reason": "Keine WAV-Konvertierung vorhanden."})
        else:
            manifest["skipped"].append({"type": "wav"})

        if wants("cover"):
            cover_path = _resolve_asset_cover_file(asset)
            if cover_path:
                arcname = f"cover/{_safe_zip_part(cover_path.stem, 'cover')}{cover_path.suffix.lower()}"
                zip_file.write(cover_path, arcname)
                manifest["included"].append({"type": "cover", "path": arcname, "source": str(cover_path)})
            elif asset.image_url:
                manifest["missing"].append({"type": "cover", "reason": "Kein lokaler Cover-Cache gefunden.", "remote_url": asset.image_url})
            else:
                manifest["missing"].append({"type": "cover", "reason": "Kein Cover vorhanden."})
        else:
            manifest["skipped"].append({"type": "cover"})

        if wants("stems"):
            stem_files = _stem_file_entries(asset)
            stem_count = 0
            stem_bpm = _asset_stem_metadata(asset).get("bpm") or _extract_bpm_from_asset(asset) or "unknown"
            for kind in ("vocals", "instrumental"):
                entry = stem_files.get(kind)
                if not isinstance(entry, dict):
                    continue
                stem_path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
                if not stem_path:
                    continue
                arcname = f"stems/{stem_path.name}"
                zip_file.write(stem_path, arcname)
                stem_count += 1
                manifest["included"].append({"type": f"stem_{kind}", "path": arcname, "bpm": stem_bpm, "source": str(stem_path)})
            if not stem_count:
                manifest["missing"].append({"type": "stems", "reason": "Keine Stem-Dateien vorhanden."})
        else:
            manifest["skipped"].append({"type": "stems"})

        if wants("srt"):
            if transcript and transcript.srt_text:
                srt_name = f"srt/{safe_title}.srt"
                zip_file.writestr(srt_name, transcript.srt_text.strip() + "\n")
                manifest["included"].append({"type": "srt", "path": srt_name})

                half_path = None
                if transcript.srt_path:
                    candidate = Path(transcript.srt_path).resolve().with_name(f"{Path(transcript.srt_path).resolve().stem}.half.srt")
                    if candidate.exists() and candidate.is_file():
                        half_path = candidate
                if half_path:
                    half_name = f"srt/{safe_title}.half.srt"
                    zip_file.writestr(half_name, half_path.read_text(encoding="utf-8").strip() + "\n")
                    manifest["included"].append({"type": "half_srt", "path": half_name})
            else:
                manifest["missing"].append({"type": "srt", "reason": "Keine erzeugte SRT vorhanden."})
        else:
            manifest["skipped"].append({"type": "srt"})

        zip_file.writestr("00_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    buffer.seek(0)
    suffix = "selected" if include else "complete"
    return buffer.getvalue(), f"{safe_title}_asset_{asset.id}_{suffix}.zip"

def _parse_bulk_asset_ids(value: str | None) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for part in str(value or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            asset_id = int(part)
        except ValueError:
            continue
        if asset_id > 0 and asset_id not in seen:
            ids.append(asset_id)
            seen.add(asset_id)
    if not ids:
        raise HTTPException(status_code=422, detail="Keine gültigen AudioAsset-IDs übergeben.")
    if len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bulk-ZIP ist auf maximal 200 Varianten begrenzt.")
    return ids


def _build_bulk_audio_asset_bundle(db: Session, asset_ids: list[int], include: set[str] | None = None) -> tuple[bytes, str]:
    rows = db.query(AudioAsset).filter(AudioAsset.id.in_(asset_ids), AudioAsset.is_deleted.is_(False)).all()
    by_id = {int(row.id): row for row in rows}
    ordered = [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]
    if not ordered:
        raise HTTPException(status_code=404, detail="Keine passenden AudioAssets gefunden.")

    first_title = ordered[0].project_title or ordered[0].display_title or ordered[0].title or "audio_varianten"
    safe_title = _safe_zip_part(first_title, "audio_varianten")
    manifest: dict[str, Any] = {
        "exported_at": utc_now_naive().isoformat(),
        "scope": "bulk_audio_assets",
        "requested_asset_ids": asset_ids,
        "included_asset_ids": [asset.id for asset in ordered],
        "requested_content": sorted(include) if include else "all",
        "variants": [],
        "missing_asset_ids": [asset_id for asset_id in asset_ids if asset_id not in by_id],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        zip_file.writestr("README.txt", "\n".join([
            f"Suno Song Studio Varianten-Paket: {first_title}",
            f"Varianten: {len(ordered)}",
            f"Exportiert: {manifest['exported_at']}",
            "",
            "Jede Variante liegt in einem eigenen Unterordner mit Manifest und den verfügbaren Inhalten.",
            "",
        ]))
        for index, asset in enumerate(ordered, start=1):
            title = asset.display_title or asset.title or asset.audio_id or f"audio_{asset.id}"
            folder = f"{index:02d}_{_safe_zip_part(title, f'audio_{asset.id}')}"
            data, _filename = _build_audio_asset_bundle(db, asset, include)
            manifest["variants"].append({
                "index": index,
                "audio_asset_id": asset.id,
                "song_id": asset.song_id,
                "title": title,
                "folder": folder,
            })
            with ZipFile(BytesIO(data), "r") as single_zip:
                for info in single_zip.infolist():
                    if info.is_dir():
                        continue
                    zip_file.writestr(f"{folder}/{info.filename}", single_zip.read(info.filename))
        zip_file.writestr("00_bulk_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    buffer.seek(0)
    return buffer.getvalue(), f"{safe_title}_all_variants_{len(ordered)}.zip"



def _dedupe_positive_ids(values: list[int] | tuple[int, ...] | None, limit: int = 250) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            asset_id = int(value)
        except (TypeError, ValueError):
            continue
        if asset_id <= 0 or asset_id in seen:
            continue
        ids.append(asset_id)
        seen.add(asset_id)
    if not ids:
        raise HTTPException(status_code=422, detail="Keine gültigen AudioAsset-IDs übergeben.")
    if len(ids) > limit:
        raise HTTPException(status_code=422, detail=f"Bulk-Aktion ist auf maximal {limit} Varianten begrenzt.")
    return ids


def _create_bulk_status_task(db: Session, *, task_type: str, title: str, message: str, asset_ids: list[int], request_payload: dict[str, Any] | None = None) -> SunoTask:
    payload = {
        "audio_asset_ids": asset_ids,
        "count": len(asset_ids),
        **(request_payload or {}),
    }
    task = SunoTask(
        task_id=None,
        task_type=task_type,
        status="RUNNING",
        request_payload={**payload, "background": True, "local_task": True},
        response_payload={"background": True, "local_task": True, "status": "RUNNING"},
        result_payload=None,
        error_message=None,
        started_at=utc_now_naive(),
        heartbeat_at=utc_now_naive(),
        completed_at=None,
        cancel_requested=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    mark_task_started(db, task)
    db.add(StatusNotification(
        event_type=f"{task_type}_started",
        title=title,
        message=message,
        severity="info",
        status="unread",
        task_local_id=task.id,
        suno_task_id=None,
        content_type="bulk_audio",
        content_id=None,
        target_tab="status",
        target_payload={"task_local_id": task.id, "task_type": task_type, "status": "RUNNING", "audio_asset_ids": asset_ids},
    ))
    db.commit()
    return task


def _finish_bulk_status_task(db: Session, task_id: int, *, task_type: str, title: str, success: int, failed: int, skipped: int = 0, errors: list[dict[str, Any]] | None = None) -> None:
    now = utc_now_naive()
    status = "SUCCESS" if failed == 0 else ("PARTIAL_SUCCESS" if success > 0 else "FAILED")
    message_parts = [f"{success} erfolgreich"]
    if failed:
        message_parts.append(f"{failed} Fehler")
    if skipped:
        message_parts.append(f"{skipped} übersprungen")
    message = " · ".join(message_parts)
    task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
    if task:
        task.status = status
        task.completed_at = now
        task.heartbeat_at = now
        task.error_message = None if failed == 0 else message
        task.result_payload = {
            "status": status,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "errors": errors or [],
            "completed_at": now.isoformat(),
        }
        final_phase = "completed" if status == "SUCCESS" else ("partial_success" if status == "PARTIAL_SUCCESS" else "failed")
        append_task_debug_event(
            db,
            task,
            event="bulk_task_finished",
            detail=message,
            level="info" if status == "SUCCESS" else ("warning" if status == "PARTIAL_SUCCESS" else "error"),
            data={
                "task_type": task_type,
                "status": status,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "errors_preview": (errors or [])[:20],
            },
            commit=False,
        )
        append_task_step_log(
            db,
            task,
            phase=final_phase,
            phase_label="Sammellauf abgeschlossen" if status == "SUCCESS" else ("Sammellauf teilweise abgeschlossen" if status == "PARTIAL_SUCCESS" else "Sammellauf fehlgeschlagen"),
            detail=message,
            data={"task_type": task_type, "status": status, "success": success, "failed": failed, "skipped": skipped},
            commit=False,
        )
        db.add(task)
        running_rows = (
            db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == f"{task_type}_started",
                StatusNotification.status != "done",
                StatusNotification.is_deleted.is_(False),
            )
            .all()
        )
        for row in running_rows:
            row.status = "done"
            row.completed_at = now
            row.message = f"Abgeschlossen: {message}"
            db.add(row)
    db.add(StatusNotification(
        event_type=f"{task_type}_completed" if failed == 0 else f"{task_type}_failed",
        title=title,
        message=message,
        severity="success" if failed == 0 else ("warning" if success > 0 else "error"),
        status="unread",
        task_local_id=task_id,
        suno_task_id=None,
        content_type="bulk_audio",
        content_id=None,
        target_tab="status",
        target_payload={"task_local_id": task_id, "task_type": task_type, "status": status, "success": success, "failed": failed, "skipped": skipped},
        completed_at=now,
    ))
    db.commit()


async def _run_bulk_srt_generation_background(master_task_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    stop_heartbeat = start_task_heartbeat(master_task_id)
    success = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    try:
        asset_ids = _dedupe_positive_ids(payload.get("ids") or [])
        admin_settings = load_transcription_admin_settings(db)
        generate_stems_first = (
            bool(payload.get("generate_vocal_stems_before_transcription"))
            if payload.get("generate_vocal_stems_before_transcription") is not None
            else bool(admin_settings.get("srt_generate_vocal_stems_before_transcription", False))
        )
        total = len(asset_ids)
        for index, asset_id in enumerate(asset_ids, start=1):
            heartbeat_task(db, master_task_id, progress={"current": index, "total": total, "audio_asset_id": asset_id, "success": success, "failed": failed})
            if is_cancel_requested(db, master_task_id):
                failed += 1
                errors.append({"audio_asset_id": asset_id, "error": "SRT-Sammellauf wurde manuell abgebrochen."})
                break
            try:
                if generate_stems_first and payload.get("prefer_existing_vocal_stem", True):
                    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
                    if asset:
                        stem_files = _stem_file_entries(asset)
                        if not isinstance(stem_files.get("vocals"), dict):
                            generate_stems_for_asset(db, asset_id)
                await generate_srt_for_audio_asset(
                    db=db,
                    audio_asset_id=asset_id,
                    manual_lyrics=None,
                    force=bool(payload.get("force", True)),
                    language_override=payload.get("language"),
                    backend_override=payload.get("backend"),
                    prefer_existing_vocal_stem=bool(payload.get("prefer_existing_vocal_stem", True)),
                )
                success += 1
            except Exception as exc:
                failed += 1
                errors.append({"audio_asset_id": asset_id, "error": getattr(exc, "detail", str(exc))})
                db.rollback()
        _finish_bulk_status_task(
            db,
            master_task_id,
            task_type="bulk_generate_srt",
            title="SRT-Sammellauf abgeschlossen",
            success=success,
            failed=failed,
            errors=errors,
        )
    except Exception as exc:
        db.rollback()
        _finish_bulk_status_task(
            db,
            master_task_id,
            task_type="bulk_generate_srt",
            title="SRT-Sammellauf fehlgeschlagen",
            success=success,
            failed=max(1, failed),
            errors=errors + [{"error": str(exc)}],
        )
    finally:
        stop_heartbeat()
        db.close()


def _run_bulk_stems_generation_background(master_task_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    stop_heartbeat = start_task_heartbeat(master_task_id)
    success = 0
    failed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    try:
        asset_ids = _dedupe_positive_ids(payload.get("ids") or [])
        total = len(asset_ids)
        for index, asset_id in enumerate(asset_ids, start=1):
            heartbeat_task(db, master_task_id, progress={"current": index, "total": total, "audio_asset_id": asset_id, "success": success, "failed": failed, "skipped": skipped})
            if is_cancel_requested(db, master_task_id):
                failed += 1
                errors.append({"audio_asset_id": asset_id, "error": "Stem-Sammellauf wurde manuell abgebrochen."})
                break
            try:
                asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
                if not asset:
                    failed += 1
                    errors.append({"audio_asset_id": asset_id, "error": "AudioAsset wurde nicht gefunden."})
                    continue
                local_path = Path(str(asset.local_path or "")).expanduser() if asset.local_path else None
                if not local_path or not local_path.exists() or not local_path.is_file():
                    skipped += 1
                    continue
                generate_stems_for_asset(db, asset_id)
                success += 1
            except Exception as exc:
                failed += 1
                errors.append({"audio_asset_id": asset_id, "error": getattr(exc, "detail", str(exc))})
                db.rollback()
        _finish_bulk_status_task(
            db,
            master_task_id,
            task_type="bulk_generate_stems",
            title="Stem-Sammellauf abgeschlossen",
            success=success,
            failed=failed,
            skipped=skipped,
            errors=errors,
        )
    except Exception as exc:
        db.rollback()
        _finish_bulk_status_task(
            db,
            master_task_id,
            task_type="bulk_generate_stems",
            title="Stem-Sammellauf fehlgeschlagen",
            success=success,
            failed=max(1, failed),
            skipped=skipped,
            errors=errors + [{"error": str(exc)}],
        )
    finally:
        stop_heartbeat()
        db.close()


def _delete_srt_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    settings = get_settings()
    rows = db.query(AudioTranscript).filter(AudioTranscript.audio_asset_id == asset.id).all()
    removed_files = 0
    removed_rows = 0
    for row in rows:
        if row.srt_path:
            if _safe_unlink(row.srt_path, settings.transcript_storage_path):
                removed_files += 1
        db.delete(row)
        removed_rows += 1
    return {"kind": "srt", "removed_rows": removed_rows, "removed_files": removed_files}


def _has_other_active_audio_file_reference(db: Session, asset: AudioAsset) -> bool:
    references = [str(value).strip() for value in (asset.local_path, asset.public_url, asset.filename) if str(value or "").strip()]
    if not references:
        return False
    return bool(
        db.query(AudioAsset.id)
        .filter(
            AudioAsset.id != asset.id,
            AudioAsset.is_deleted.is_(False),
            or_(
                AudioAsset.local_path.in_(references),
                AudioAsset.public_url.in_(references),
                AudioAsset.filename.in_(references),
            ),
        )
        .first()
    )


def _has_other_active_cover_reference(db: Session, asset: AudioAsset, public_url: str | None) -> bool:
    if not public_url:
        return False
    if (
        db.query(AudioAsset.id)
        .filter(
            AudioAsset.id != asset.id,
            AudioAsset.is_deleted.is_(False),
            AudioAsset.image_url == public_url,
        )
        .first()
    ):
        return True
    if (
        db.query(Song.id)
        .filter(
            Song.is_deleted.is_(False),
            Song.id != asset.song_id if asset.song_id else True,
            Song.cover_image_url == public_url,
        )
        .first()
    ):
        return True
    return bool(
        db.query(AudioProject.id)
        .filter(
            AudioProject.is_deleted.is_(False),
            AudioProject.id != asset.project_id if asset.project_id else True,
            AudioProject.cover_image_url == public_url,
        )
        .first()
    )


def _delete_audio_file_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    settings = get_settings()
    shared_reference = _has_other_active_audio_file_reference(db, asset)
    removed = False if shared_reference else _safe_unlink(asset.local_path, settings.audio_storage_path)
    old_public_url = asset.public_url
    asset.local_path = None
    asset.public_url = None
    asset.filename = None
    asset.file_size_bytes = None
    asset.checksum_sha256 = None
    asset.waveform_json = None
    asset.waveform_generated_at = None
    asset.status = "remote" if asset.source_url else "missing"
    return {"kind": "audio", "removed_files": 1 if removed else 0, "old_public_url": old_public_url, "shared_reference": shared_reference}


def _delete_wav_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    wav_path = _resolve_asset_wav_file(asset)
    removed_files = 0
    if wav_path and asset.local_path and Path(asset.local_path).expanduser().resolve() == wav_path.expanduser().resolve():
        removed_files = 0
    elif wav_path and _safe_unlink(str(wav_path), get_settings().audio_storage_path):
        removed_files = 1
    metadata = _safe_metadata(asset.metadata_json)
    existed = "wav_conversion" in metadata
    metadata.pop("wav_conversion", None)
    asset.metadata_json = metadata
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id).first()
        if song:
            song.wav_url = None
            song_metadata = _safe_metadata(song.metadata_json)
            song_metadata.pop("wav_conversion", None)
            song.metadata_json = song_metadata
    return {"kind": "wav", "removed": existed, "removed_files": removed_files}


def _delete_cover_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    settings = get_settings()
    removed_files = 0
    metadata = _safe_metadata(asset.metadata_json)
    cover_cache = metadata.get("cover_cache") if isinstance(metadata.get("cover_cache"), dict) else None
    public_url = None
    if cover_cache:
        public_url = cover_cache.get("public_url")
    if not public_url and asset.image_url and str(asset.image_url).startswith(settings.suno_cover_public_route.rstrip("/") + "/"):
        public_url = asset.image_url
    path = _path_from_public_url(public_url, settings.suno_cover_public_route, settings.cover_storage_path)
    shared_reference = _has_other_active_cover_reference(db, asset, public_url)
    if path and not shared_reference and _safe_unlink(str(path), settings.cover_storage_path):
        removed_files += 1
    if "cover_cache" in metadata:
        metadata.pop("cover_cache", None)
    if asset.image_url and str(asset.image_url).startswith(settings.suno_cover_public_route.rstrip("/") + "/"):
        asset.image_url = metadata.get("source_image_url") or None
    asset.metadata_json = metadata
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id).first()
        if song:
            song_metadata = _safe_metadata(song.metadata_json)
            song_cover_cache = song_metadata.get("cover_cache") if isinstance(song_metadata.get("cover_cache"), dict) else None
            if song_cover_cache and song_cover_cache.get("public_url") == public_url:
                song_metadata.pop("cover_cache", None)
                song.metadata_json = song_metadata
            if song.cover_image_url and str(song.cover_image_url).startswith(settings.suno_cover_public_route.rstrip("/") + "/"):
                song.cover_image_url = song_metadata.get("source_image_url") or None
    return {"kind": "cover", "removed_files": removed_files, "shared_reference": shared_reference}


def _delete_timestamped_lyrics_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    metadata = _safe_metadata(asset.metadata_json)
    existed = "timestamped_lyrics" in metadata
    metadata.pop("timestamped_lyrics", None)
    metadata.pop("timestampedLyrics", None)
    asset.metadata_json = metadata
    return {"kind": "timestamped_lyrics", "removed": existed}


def _delete_waveform_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    existed = bool(asset.waveform_json)
    asset.waveform_json = None
    asset.waveform_generated_at = None
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id).first()
        if song:
            song.waveform_json = None
            song.waveform_generated_at = None
    return {"kind": "waveform", "removed": existed}


def _delete_structure_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    existed = bool(asset.structure_segments_json)
    asset.structure_segments_json = None
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id).first()
        if song:
            song.structure_segments_json = None
    return {"kind": "structure", "removed": existed}


def _delete_stems_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    files = _stem_file_entries(asset)
    removed_files = 0
    for entry in files.values():
        if not isinstance(entry, dict):
            continue
        path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
        if path and _safe_unlink(str(path), _stem_storage_path()):
            removed_files += 1
    metadata = _safe_metadata(asset.metadata_json)
    existed = "stems" in metadata
    metadata.pop("stems", None)
    asset.metadata_json = metadata
    return {"kind": "stems", "removed": existed, "removed_files": removed_files}


def _delete_lyrics_content(db: Session, asset: AudioAsset) -> dict[str, Any]:
    metadata = _safe_metadata(asset.metadata_json)
    removed_keys: list[str] = []
    for key in ("lyrics", "text", "prompt"):
        if key in metadata:
            metadata.pop(key, None)
            removed_keys.append(key)
    for nested_key in ("candidate", "request_payload"):
        nested = metadata.get(nested_key)
        if isinstance(nested, dict):
            for key in ("lyrics", "text", "prompt"):
                if key in nested:
                    nested.pop(key, None)
                    removed_keys.append(f"{nested_key}.{key}")
    asset.metadata_json = metadata
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id).first()
        if song:
            if song.lyrics:
                removed_keys.append("songs.lyrics")
            if song.prompt:
                removed_keys.append("songs.prompt")
            song.lyrics = None
            song.prompt = None
    return {"kind": "lyrics", "removed_keys": sorted(set(removed_keys))}


def delete_audio_asset_content(db: Session, audio_asset_id: int, kind: str) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    normalized = str(kind or "").strip().lower().replace("-", "_")
    handlers = {
        "srt": _delete_srt_content,
        "transcript": _delete_srt_content,
        "audio": _delete_audio_file_content,
        "audio_file": _delete_audio_file_content,
        "wav": _delete_wav_content,
        "wave": _delete_wav_content,
        "convert_to_wav": _delete_wav_content,
        "cover": _delete_cover_content,
        "image": _delete_cover_content,
        "timestamped_lyrics": _delete_timestamped_lyrics_content,
        "timestamped": _delete_timestamped_lyrics_content,
        "waveform": _delete_waveform_content,
        "structure": _delete_structure_content,
        "segments": _delete_structure_content,
        "stems": _delete_stems_content,
        "stem": _delete_stems_content,
        "vocals": _delete_stems_content,
        "instrumental": _delete_stems_content,
        "lyrics": _delete_lyrics_content,
        "songtext": _delete_lyrics_content,
    }
    handler = handlers.get(normalized)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Dieser Einzelinhalt kann nicht gelöscht werden: {kind}")
    result = handler(db, asset)
    db.commit()
    return {"ok": True, "audio_asset_id": audio_asset_id, **result}




def _short_text_hash(value: Any) -> str | None:
    text = str(value or "")
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _set_nested_text_fields(container: dict[str, Any], *, lyrics: str, prompt: str) -> None:
    container["lyrics"] = lyrics
    container["text"] = lyrics
    container["prompt"] = prompt



def _sync_parent_favorite_state(db: Session, asset: AudioAsset) -> tuple[bool | None, bool | None]:
    song_favorite: bool | None = None
    project_favorite: bool | None = None
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if song:
            song_favorite = db.query(AudioAsset).filter(
                AudioAsset.song_id == asset.song_id,
                AudioAsset.is_deleted.is_(False),
                AudioAsset.is_favorite.is_(True),
            ).first() is not None
            song.is_favorite = bool(song_favorite)
            db.add(song)
    if asset.project_id:
        project = db.query(AudioProject).filter(AudioProject.id == asset.project_id, AudioProject.is_deleted.is_(False)).first()
        if project:
            project_favorite = db.query(AudioAsset).filter(
                AudioAsset.project_id == asset.project_id,
                AudioAsset.is_deleted.is_(False),
                AudioAsset.is_favorite.is_(True),
            ).first() is not None
            project.is_favorite = bool(project_favorite)
            db.add(project)
    return song_favorite, project_favorite


@router.get("/favorites", response_model=list[AudioAssetRead])
def list_favorite_audio_assets(limit: int = 250, db: Session = Depends(get_db)):
    safe_limit = max(1, min(int(limit or 250), 500))
    return [asset for asset in active_usable_audio_assets(db, limit=max(safe_limit, 500)) if bool(asset.is_favorite)][:safe_limit]


@router.patch("/{audio_asset_id}/favorite")
def update_audio_asset_favorite(audio_asset_id: int, payload: FavoriteAssetRequest, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    previous = bool(asset.is_favorite)
    asset.is_favorite = bool(payload.is_favorite)
    metadata = _safe_metadata(asset.metadata_json)
    metadata["favorite"] = {
        "is_favorite": bool(asset.is_favorite),
        "updated_at": utc_now_naive().isoformat(),
        "source": "library_thumb_up",
    }
    asset.metadata_json = metadata
    db.add(asset)
    db.flush()
    song_favorite, project_favorite = _sync_parent_favorite_state(db, asset)
    db.add(ActivityLog(
        action="audio_asset_favorite_updated",
        content_type="audio_asset",
        content_id=asset.id,
        old_value={"is_favorite": previous},
        new_value={"is_favorite": bool(asset.is_favorite)},
        metadata_json={"song_id": asset.song_id, "project_id": asset.project_id},
    ))
    db.commit()
    db.refresh(asset)
    return {
        "ok": True,
        "audio_asset_id": asset.id,
        "song_id": asset.song_id,
        "project_id": asset.project_id,
        "is_favorite": bool(asset.is_favorite),
        "song_is_favorite": song_favorite,
        "project_is_favorite": project_favorite,
        "message": "Favorit gespeichert." if asset.is_favorite else "Favorit entfernt.",
    }


@router.patch("/{audio_asset_id}/lyrics", response_model=AudioAssetRead)
def update_audio_asset_lyrics(audio_asset_id: int, payload: UpdateAssetLyricsRequest, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    clean_lyrics = str(payload.lyrics or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean_lyrics:
        raise HTTPException(status_code=422, detail="Songtext darf nicht leer sein.")
    clean_prompt = str(payload.prompt if payload.prompt is not None else clean_lyrics).replace("\r\n", "\n").replace("\r", "\n").strip() or clean_lyrics

    metadata = _safe_metadata(asset.metadata_json)
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    previous = {
        "asset_id": asset.id,
        "song_id": asset.song_id,
        "candidate_lyrics_sha256": _short_text_hash(candidate.get("lyrics")),
        "candidate_prompt_sha256": _short_text_hash(candidate.get("prompt")),
        "request_lyrics_sha256": _short_text_hash(request_payload.get("lyrics")),
        "request_prompt_sha256": _short_text_hash(request_payload.get("prompt")),
        "asset_prompt_sha256": _short_text_hash(asset.prompt),
        "asset_lyrics_sha256": _short_text_hash(asset.lyrics),
    }

    _set_nested_text_fields(candidate, lyrics=clean_lyrics, prompt=clean_prompt)
    _set_nested_text_fields(request_payload, lyrics=clean_lyrics, prompt=clean_prompt)
    metadata["candidate"] = candidate
    metadata["request_payload"] = request_payload
    metadata["lyrics"] = clean_lyrics
    metadata["prompt"] = clean_prompt
    metadata["lyrics_manual_override"] = {
        "enabled": True,
        "updated_at": utc_now_naive().isoformat(),
        "source": "library_songdetail_editor",
        "lyrics_sha256": _short_text_hash(clean_lyrics),
        "prompt_sha256": _short_text_hash(clean_prompt),
        "lyrics_length": len(clean_lyrics),
        "prompt_length": len(clean_prompt),
    }
    asset.metadata_json = metadata

    song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
    if song:
        song.prompt = clean_prompt
        song.lyrics = clean_lyrics
        song.metadata_json = metadata
        db.add(song)

    db.add(asset)
    db.add(ActivityLog(
        action="audio_asset_lyrics_updated",
        content_type="audio_asset",
        content_id=asset.id,
        old_value=previous,
        new_value={
            "asset_id": asset.id,
            "song_id": asset.song_id,
            "lyrics_sha256": _short_text_hash(clean_lyrics),
            "prompt_sha256": _short_text_hash(clean_prompt),
            "lyrics_length": len(clean_lyrics),
            "prompt_length": len(clean_prompt),
        },
        metadata_json={
            "source": "library_songdetail_editor",
            "affects_srt_source_of_truth": True,
        },
    ))
    db.commit()
    db.refresh(asset)
    return AudioAssetRead.model_validate(asset)


@router.post("/manual-import", response_model=dict)
def import_manual_audio_asset(
    audio: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    title: str = Form(...),
    lyrics: str | None = Form(default=None),
    style: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    project_title: str | None = Form(default=None),
    language: str | None = Form(default="de"),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    clean_title = str(title or "").strip()
    if not clean_title:
        raise HTTPException(status_code=422, detail="Titel ist erforderlich.")
    if not audio or not audio.filename:
        raise HTTPException(status_code=422, detail="Audiodatei ist erforderlich.")

    extension = _validate_upload_extension(audio.filename, settings.audio_allowed_extensions_list, "Audio")
    if audio.content_type and audio.content_type.lower() not in settings.audio_allowed_content_types_list:
        # Browser liefern je nach System gelegentlich application/octet-stream. Dieser Typ ist bewusst erlaubt.
        raise HTTPException(status_code=422, detail=f"Ungültiger Audio-Content-Type: {audio.content_type}")

    asset_token = uuid.uuid4().hex[:12]
    audio_root = settings.audio_storage_path
    safe_stem = _sanitize_upload_stem(clean_title, "manual_audio")
    audio_filename = f"{safe_stem}_{asset_token}{extension}"
    target_audio = (audio_root / audio_filename).resolve()
    if not _is_relative_to(target_audio, settings.audio_storage_path.resolve()):
        raise HTTPException(status_code=400, detail="Ungültiger Audio-Speicherpfad.")

    file_size, checksum = _write_upload_file(audio, target_audio, settings.audio_max_download_bytes)
    content_type = normalize_audio_content_type(audio.content_type, target_audio)
    duration = read_audio_duration_seconds(target_audio)
    public_url = _public_url_for_storage_file(target_audio, settings.audio_storage_path, settings.suno_audio_public_route)

    cover_info = _write_optional_cover(cover, clean_title, asset_token)
    image_url = cover_info.get("public_url") if cover_info else None
    clean_lyrics = str(lyrics or "").strip()
    clean_prompt = str(prompt or "").strip() or clean_lyrics
    clean_style = str(style or "").strip()
    clean_language = str(language or "de").strip().lower() or "de"
    clean_project_title = str(project_title or "").strip() or clean_title

    now_iso = utc_now_naive().isoformat()
    metadata: dict[str, Any] = {
        "source": "manual_import",
        "manual_import": {
            "imported_at": now_iso,
            "original_audio_filename": audio.filename,
            "original_cover_filename": cover.filename if cover and cover.filename else None,
            "language": clean_language,
            "notes": str(notes or "").strip() or None,
        },
        "candidate": {
            "title": clean_title,
            "lyrics": clean_lyrics or None,
            "text": clean_lyrics or None,
            "prompt": clean_prompt or None,
            "style": clean_style or None,
            "tags": clean_style or None,
            "model": "manual_import",
        },
        "request_payload": {
            "title": clean_title,
            "lyrics": clean_lyrics or None,
            "prompt": clean_prompt or None,
            "style": clean_style or None,
            "tags": clean_style or None,
            "language": clean_language,
        },
        "audio_cache": {
            "local_path": to_portable_path(target_audio, storage_root=settings.audio_storage_path),
            "public_url": public_url,
            "filename": audio_filename,
            "content_type": content_type,
            "file_size_bytes": file_size,
            "checksum_sha256": checksum,
        },
    }
    if cover_info:
        metadata["cover_cache"] = cover_info
        metadata["source_image_url"] = image_url

    project = AudioProject(
        title=clean_project_title,
        description="Manuell importiertes Audio-Projekt",
        cover_image_url=image_url,
        status="active",
        metadata_json={"source": "manual_import", "imported_at": now_iso},
    )
    db.add(project)
    db.flush()

    song = Song(
        title=clean_title,
        model="manual_import",
        prompt=clean_prompt or None,
        lyrics=clean_lyrics or None,
        audio_url=public_url,
        cover_image_url=image_url,
        project_id=project.id,
        metadata_json=metadata,
    )
    db.add(song)
    db.flush()

    asset = AudioAsset(
        task_local_id=None,
        song_id=song.id,
        suno_task_id=None,
        audio_id=f"manual-{asset_token}",
        title=clean_title,
        display_title=clean_title,
        image_url=image_url,
        source_url=public_url,
        local_path=to_portable_path(target_audio, storage_root=settings.audio_storage_path),
        public_url=public_url,
        filename=audio_filename,
        content_type=content_type,
        file_size_bytes=file_size,
        duration_seconds=int(duration) if duration else None,
        checksum_sha256=checksum,
        status="cached",
        metadata_json=metadata,
        project_id=project.id,
        operation_label="Manuell importiert",
        version_label="Manuell",
        is_final=True,
    )
    db.add(asset)
    db.flush()
    project.final_audio_asset_id = asset.id
    db.add(project)
    db.commit()
    db.refresh(asset)

    return {
        "ok": True,
        "message": "Audio wurde manuell importiert.",
        "audio_asset_id": asset.id,
        "project_id": project.id,
        "song_id": song.id,
        "audio_id": asset.audio_id,
        "title": asset.title,
        "public_url": asset.public_url,
        "cover_url": asset.image_url,
        "status": asset.status,
        "source": "manual_import",
    }




def _run_single_srt_generation_background(task_id: int, audio_asset_id: int, payload_data: dict[str, Any]) -> None:
    async def _run() -> None:
        db = SessionLocal()
        try:
            task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
            heartbeat_task(db, task_id, progress={"current": 1, "total": 1, "audio_asset_id": audio_asset_id})
            if is_cancel_requested(db, task_id):
                raise RuntimeError("SRT-Erzeugung wurde vor dem Start abgebrochen.")
            payload = GenerateSrtRequest(**(payload_data or {}))
            await generate_srt_for_audio_asset(
                db=db,
                audio_asset_id=audio_asset_id,
                manual_lyrics=payload.lyrics_override,
                force=payload.force,
                language_override=payload.language,
                backend_override=payload.backend,
                prefer_existing_vocal_stem=payload.prefer_existing_vocal_stem,
                status_task=task,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    asyncio.run(_run())


def _run_single_stems_generation_background(task_id: int, audio_asset_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
        heartbeat_task(db, task_id, progress={"current": 1, "total": 1, "audio_asset_id": audio_asset_id})
        if is_cancel_requested(db, task_id):
            raise RuntimeError("Stem-Erzeugung wurde vor dem Start abgebrochen.")
        generate_stems_for_asset(db, audio_asset_id, status_task=task)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_audio_ai_analysis_background(task_id: int, audio_asset_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
        heartbeat_task(db, task_id, progress={"current": 1, "total": 5, "phase": "queued", "audio_asset_id": audio_asset_id})
        if is_cancel_requested(db, task_id):
            raise RuntimeError("Audioanalyse wurde vor dem Start abgebrochen.")
        options = AudioAiAnalysisOptions(
            profile=str(payload.get("profile") or "standard"),
            include_ai_report=bool(payload.get("include_ai_report", True)),
            force=bool(payload.get("force", False)),
        )
        run_audio_ai_analysis(db, audio_asset_id, options=options, task=task)
    except Exception as exc:
        db.rollback()
        try:
            fail_audio_ai_analysis_task(db, task_id, audio_asset_id, str(exc))
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


async def _run_library_ai_tagging_background(task_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    stop_heartbeat = start_task_heartbeat(task_id)
    success = 0
    failed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    tagged_ids: list[int] = []
    try:
        asset_ids = _dedupe_positive_ids(payload.get("ids") or payload.get("audio_asset_ids") or [])
        force = bool(payload.get("force", False))
        total = len(asset_ids)
        for index, asset_id in enumerate(asset_ids, start=1):
            heartbeat_task(db, task_id, progress={"current": index, "total": total, "audio_asset_id": asset_id, "success": success, "failed": failed, "skipped": skipped})
            if is_cancel_requested(db, task_id):
                skipped += max(0, total - index + 1)
                break
            asset = db.query(AudioAsset).filter(AudioAsset.id == int(asset_id), AudioAsset.is_deleted.is_(False)).first()
            if not asset:
                failed += 1
                errors.append({"audio_asset_id": asset_id, "error": "AudioAsset wurde nicht gefunden."})
                continue
            if read_saved_library_ai_tags(asset) and not force:
                skipped += 1
                tagged_ids.append(asset.id)
                continue
            try:
                await generate_library_ai_tags_for_asset(db, asset, force=force)
                success += 1
                tagged_ids.append(asset.id)
            except Exception as exc:
                db.rollback()
                failed += 1
                errors.append({"audio_asset_id": asset.id, "error": str(exc)})
        finish_library_ai_tagging_status_task(db, task_id, success=success, failed=failed, skipped=skipped, errors=errors[:20], tagged_ids=tagged_ids)
    except Exception as exc:
        db.rollback()
        finish_library_ai_tagging_status_task(db, task_id, success=success, failed=max(1, failed), skipped=skipped, errors=[*errors[:19], {"error": str(exc)}], tagged_ids=tagged_ids)
        raise
    finally:
        stop_heartbeat()
        db.close()


@router.post("/{audio_asset_id}/wav/convert")
def convert_audio_asset_wav(audio_asset_id: int, payload: ConvertAssetWavRequest | None = None, db: Session = Depends(get_db)):
    return convert_asset_to_wav(db, audio_asset_id, force=bool(payload.force) if payload else False)



@router.post("/bulk/srt/generate")
def bulk_generate_srt(payload: BulkGenerateSrtRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    asset_ids = _dedupe_positive_ids(payload.ids)
    task = _create_bulk_status_task(
        db,
        task_type="bulk_generate_srt",
        title="SRT-Sammellauf gestartet",
        message=f"SRT-Erzeugung für {len(asset_ids)} Varianten läuft im Hintergrund.",
        asset_ids=asset_ids,
        request_payload={
            "force": payload.force,
            "language": payload.language,
            "backend": payload.backend,
            "prefer_existing_vocal_stem": payload.prefer_existing_vocal_stem,
            "generate_vocal_stems_before_transcription": payload.generate_vocal_stems_before_transcription,
        },
    )
    run_detached_process(f"bulk-srt-{task.id}", _run_bulk_srt_generation_background, task.id, {**payload.model_dump(), "ids": asset_ids})
    return {
        "task_local_id": task.id,
        "task_type": "bulk_generate_srt",
        "status": "RUNNING",
        "count": len(asset_ids),
        "message": "SRT-Sammellauf wurde gestartet und läuft im Hintergrund.",
    }


@router.post("/bulk/stems/generate")
def bulk_generate_stems(payload: BulkGenerateStemsRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    asset_ids = _dedupe_positive_ids(payload.ids)
    task = _create_bulk_status_task(
        db,
        task_type="bulk_generate_stems",
        title="Stem-Sammellauf gestartet",
        message=f"Stem-Erzeugung für {len(asset_ids)} Varianten läuft im Hintergrund.",
        asset_ids=asset_ids,
    )
    run_detached_process(f"bulk-stems-{task.id}", _run_bulk_stems_generation_background, task.id, {"ids": asset_ids})
    return {
        "task_local_id": task.id,
        "task_type": "bulk_generate_stems",
        "status": "RUNNING",
        "count": len(asset_ids),
        "message": "Stem-Sammellauf wurde gestartet und läuft im Hintergrund.",
    }


@router.post("/bulk/ai-tags/generate")
def bulk_generate_library_ai_tags(payload: BulkLibraryAiTaggingRequest, db: Session = Depends(get_db)):
    settings = load_library_ai_tagging_settings(db)
    if not settings.get("enabled"):
        raise HTTPException(status_code=403, detail="KI-Tagging ist im Admin-Panel deaktiviert.")
    asset_ids = _dedupe_positive_ids(payload.ids)
    if not asset_ids:
        raise HTTPException(status_code=422, detail="Keine gültigen AudioAsset-IDs übergeben.")
    task = create_library_ai_tagging_status_task(db, None, asset_ids=asset_ids, force=bool(payload.force))
    run_detached_process(f"bulk-library-ai-tags-{task.id}", _run_library_ai_tagging_background, task.id, {"ids": asset_ids, "force": bool(payload.force)})
    return {
        "ok": True,
        "queued": True,
        "task_local_id": task.id,
        "task_type": "bulk_library_ai_tagging",
        "status": "RUNNING",
        "count": len(asset_ids),
        "message": "KI-Tagging-Sammellauf wurde gestartet und läuft im Hintergrund.",
    }


@router.get("/bulk/bundle/download")
def download_bulk_audio_asset_bundle(ids: str, include: str | None = None, db: Session = Depends(get_db)):
    asset_ids = _parse_bulk_asset_ids(ids)
    data, filename = _build_bulk_audio_asset_bundle(db, asset_ids, _parse_bundle_include(include))
    return StreamingResponse(
        BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{audio_asset_id}/wav/download")
def download_audio_asset_wav(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    wav_path = _resolve_asset_wav_file(asset)
    if not wav_path:
        raise HTTPException(status_code=404, detail="Für dieses AudioAsset wurde noch keine WAV-Datei erzeugt.")
    filename = f"{_safe_zip_part(asset.display_title or asset.title or wav_path.stem, f'audio_{asset.id}')}.wav"
    return FileResponse(wav_path, media_type="audio/wav", filename=filename)


@router.get("/{audio_asset_id}/bundle/download")
def download_audio_asset_bundle(audio_asset_id: int, include: str | None = None, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    data, filename = _build_audio_asset_bundle(db, asset, _parse_bundle_include(include))
    return StreamingResponse(
        BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



@router.post("/{audio_asset_id}/stems/generate")
def generate_stems(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    task = _create_stem_status_task(db, asset)
    mark_task_started(db, task, payload={"audio_asset_id": audio_asset_id})
    run_detached_process(f"stems-asset-{audio_asset_id}-{task.id}", _run_single_stems_generation_background, task.id, audio_asset_id)
    return {"ok": True, "queued": True, "task_local_id": task.id, "task_type": "generate_stems", "status": "RUNNING", "audio_asset_id": audio_asset_id, "message": "Stem-Erzeugung wurde gestartet und läuft im Hintergrund."}


@router.get("/{audio_asset_id}/analysis")
def read_audio_ai_analysis(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    analysis = read_saved_audio_ai_analysis(asset)
    return {"exists": bool(analysis), "audio_asset_id": audio_asset_id, "analysis": analysis}


@router.get("/{audio_asset_id}/ai-tags")
def read_library_ai_tags(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    tags = read_saved_library_ai_tags(asset)
    return {"exists": bool(tags), "audio_asset_id": audio_asset_id, "ai_tags": tags}


@router.post("/{audio_asset_id}/ai-tags/generate")
def generate_library_ai_tags(audio_asset_id: int, payload: LibraryAiTaggingRequest | None = None, db: Session = Depends(get_db)):
    settings = load_library_ai_tagging_settings(db)
    if not settings.get("enabled"):
        raise HTTPException(status_code=403, detail="KI-Tagging ist im Admin-Panel deaktiviert.")
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    request = payload or LibraryAiTaggingRequest()
    existing = read_saved_library_ai_tags(asset)
    if existing and not request.force:
        return {"ok": True, "queued": False, "status": "SUCCESS", "audio_asset_id": audio_asset_id, "ai_tags": existing, "message": "KI-Tags sind bereits vorhanden."}
    task = create_library_ai_tagging_status_task(db, asset, asset_ids=[asset.id], force=bool(request.force))
    run_detached_process(f"library-ai-tags-{audio_asset_id}-{task.id}", _run_library_ai_tagging_background, task.id, {"ids": [asset.id], "force": bool(request.force)})
    return {"ok": True, "queued": True, "task_local_id": task.id, "task_type": "library_ai_tagging", "status": "RUNNING", "audio_asset_id": audio_asset_id, "message": "KI-Tagging wurde gestartet und läuft im Hintergrund."}


@router.post("/{audio_asset_id}/analysis/generate")
def generate_audio_ai_analysis(audio_asset_id: int, payload: AudioAiAnalysisRequest | None = None, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    admin_settings = load_audio_ai_analysis_admin_settings(db)
    if not admin_settings.get("enabled", True):
        raise HTTPException(status_code=403, detail="Audioanalyse ist im Admin-Panel deaktiviert.")
    request = payload or AudioAiAnalysisRequest()
    options = AudioAiAnalysisOptions(profile=request.profile, include_ai_report=request.include_ai_report, force=request.force)
    existing = read_saved_audio_ai_analysis(asset)
    if existing and not options.force:
        return {"ok": True, "queued": False, "status": "SUCCESS", "audio_asset_id": audio_asset_id, "analysis": existing, "message": "Audioanalyse ist bereits vorhanden."}
    task = create_audio_ai_status_task(db, asset, options)
    run_detached_process(f"audio-ai-analysis-{audio_asset_id}-{task.id}", _run_audio_ai_analysis_background, task.id, audio_asset_id, request.model_dump())
    return {"ok": True, "queued": True, "task_local_id": task.id, "task_type": "audio_ai_analysis", "status": "RUNNING", "audio_asset_id": audio_asset_id, "message": "Audioanalyse wurde gestartet und läuft im Hintergrund."}


@router.get("/{audio_asset_id}/analysis/export/{kind}")
def download_audio_ai_analysis_export(audio_asset_id: int, kind: str, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    try:
        path, filename, media_type = resolve_audio_ai_export_path(asset, kind)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/{audio_asset_id}/stems")
def read_stems(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    return _stem_download_payload(asset)


@router.get("/{audio_asset_id}/stems/download")
def download_stems_zip(audio_asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    if not _stem_download_payload(asset).get("exists"):
        raise HTTPException(status_code=404, detail="Keine Stem-Dateien vorhanden.")
    data, filename = _build_stems_zip(asset)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{audio_asset_id}/stems/{kind}/download")
def download_single_stem(audio_asset_id: int, kind: str, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    normalized = str(kind or "").strip().lower()
    if normalized not in {"vocals", "instrumental"}:
        raise HTTPException(status_code=400, detail="Ungültiger Stem-Typ.")
    entry = _stem_file_entries(asset).get(normalized)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="Stem-Datei wurde nicht gefunden.")
    path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
    if not path:
        raise HTTPException(status_code=404, detail="Stem-Datei wurde nicht gefunden.")
    return FileResponse(path, media_type="audio/wav", filename=entry.get("filename") or path.name)


@router.get("/{audio_asset_id}/stems/{kind}/stream")
def stream_single_stem(audio_asset_id: int, kind: str, request: Request, db: Session = Depends(get_db)):
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    normalized = str(kind or "").strip().lower()
    if normalized not in {"vocals", "instrumental"}:
        raise HTTPException(status_code=400, detail="Ungültiger Stem-Typ.")
    entry = _stem_file_entries(asset).get(normalized)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="Stem-Datei wurde nicht gefunden.")
    path = _resolve_file_inside_roots(entry.get("local_path") or entry.get("filename"), [_stem_storage_path()])
    if not path:
        raise HTTPException(status_code=404, detail="Stem-Datei wurde nicht gefunden.")
    return _inline_streaming_file_response(
        path,
        request,
        media_type=entry.get("content_type") or mimetypes.guess_type(path.name)[0] or "audio/wav",
        filename=entry.get("filename") or path.name,
    )


@router.post("/{audio_asset_id}/srt/generate")
def generate_srt(audio_asset_id: int, payload: GenerateSrtRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or GenerateSrtRequest()
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    admin_settings = load_transcription_admin_settings(db)
    backend = str(payload.backend or admin_settings.get("transcription_backend") or "groq").strip().lower()
    language = str(payload.language or admin_settings.get("transcription_language") or "auto").strip().lower()
    task = _create_srt_status_task(db, asset, backend, language, None, None, None)
    mark_task_started(db, task, payload={"audio_asset_id": audio_asset_id, "force": payload.force})
    run_detached_process(f"srt-asset-{audio_asset_id}-{task.id}", _run_single_srt_generation_background, task.id, audio_asset_id, payload.model_dump())
    return {"ok": True, "queued": True, "task_local_id": task.id, "task_type": "generate_srt", "status": "RUNNING", "audio_asset_id": audio_asset_id, "message": "SRT-Erzeugung wurde gestartet und läuft im Hintergrund."}


@router.get("/{audio_asset_id}/srt")
def read_srt(audio_asset_id: int, db: Session = Depends(get_db)):
    return get_saved_transcript(db, audio_asset_id)


@router.put("/{audio_asset_id}/srt")
def update_srt(audio_asset_id: int, payload: UpdateSrtRequest, db: Session = Depends(get_db)):
    return save_manual_srt_for_audio_asset(
        db=db,
        audio_asset_id=audio_asset_id,
        srt_text=payload.srt_text,
        segments=[segment.model_dump() for segment in payload.segments] if payload.segments is not None else None,
    )


@router.delete("/{audio_asset_id}/content/{kind}")
def delete_asset_content(audio_asset_id: int, kind: str, payload: DeleteAssetContentRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or DeleteAssetContentRequest(confirm=False)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Löschen wurde nicht bestätigt.")
    return delete_audio_asset_content(db, audio_asset_id, kind)


@router.get("/{audio_asset_id}/srt/download")
def download_srt(audio_asset_id: int, db: Session = Depends(get_db)):
    path, filename = get_transcript_download_path(db, audio_asset_id)
    return FileResponse(
        path,
        media_type="application/x-subrip; charset=utf-8",
        filename=filename,
    )


@router.get("/{audio_asset_id}/srt/half/download")
def download_half_srt(audio_asset_id: int, db: Session = Depends(get_db)):
    path, filename = get_half_transcript_download_path(db, audio_asset_id)
    return FileResponse(
        path,
        media_type="application/x-subrip; charset=utf-8",
        filename=filename,
    )
