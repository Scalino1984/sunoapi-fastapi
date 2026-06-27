from __future__ import annotations

from pathlib import Path
from datetime import datetime
import mimetypes
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ActivityLog, AudioAsset, Song, StatusNotification
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.waveform_service import get_or_create_waveform, sanitize_waveform_payload_for_asset
from app.services.audio_asset_repair_service import active_usable_audio_assets, repair_audio_library, repair_local_file_metadata, is_bad_image_asset, attach_audio_asset_identity_context
from app.services.asset_capabilities import blocked_followup_reason
from app.schemas import (
    ArchiveAudioAddInstrumentalRequest,
    ArchiveAudioAddVocalsRequest,
    ArchiveAudioCoverImageRequest,
    ArchiveAudioCoverSongRequest,
    ArchiveAudioExtendRequest,
    ArchiveAudioPersonaRequest,
    AudioAssetRead,
    AudioWaveformRead,
    TaskRead,
)
from app.services.music_service import MusicService
from app.services.audio_cache_service import AudioCacheService, AudioCandidate, CoverCacheService
from app.services.audio_asset_materialization_service import AudioAssetMaterializationService
from app.services.replicate_cover_service import MODELS as REPLICATE_COVER_MODELS, ReplicateCoverService
from app.services.library_content_cache_service import cache_missing_library_content_once
from app.services.extend_continue_at_analysis_service import analyze_continue_at_for_asset, load_extend_continue_at_settings
from app.services.system_status_notification_service import create_system_status_notification
from app.suno_client import SunoAPIClient, SunoAPIError
from app.utils.time_utils import utc_now_naive


router = APIRouter(prefix="/api/archive", tags=["archive"])


def _valid_continue_at(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _run_auto_continue_at_analysis_for_asset(db: Session, asset: AudioAsset) -> dict[str, Any]:
    settings = load_extend_continue_at_settings(db)
    if not settings.enabled:
        raise HTTPException(status_code=400, detail="Automatische continueAt-Analyse ist im Adminbereich deaktiviert.")

    create_system_status_notification(
        db,
        event_type="extend_continue_at_analysis_started",
        title="Extend-continueAt-Analyse gestartet",
        message=f"AudioAsset #{asset.id} wird für den optimalen Extend-Zeitpunkt analysiert.",
        severity="info",
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "status": "RUNNING"},
        content_type="audio_asset",
        content_id=asset.id,
    )
    result = analyze_continue_at_for_asset(asset, settings)
    create_system_status_notification(
        db,
        event_type="extend_continue_at_analysis_completed",
        title="Extend-continueAt berechnet",
        message=f"Optimierter continueAt-Wert: {result.continue_at:.3f}s ({result.method}).",
        severity="success" if result.confidence >= 0.5 else "warning",
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "status": "SUCCESS", "analysis": result.to_payload()},
        content_type="audio_asset",
        content_id=asset.id,
    )
    return result.to_payload()


def _apply_auto_continue_at_for_archive_extend(db: Session, asset: AudioAsset, request_payload: dict[str, Any]) -> dict[str, Any] | None:
    auto_requested = bool(request_payload.pop("autoContinueAt", False))
    if not auto_requested:
        return None

    settings = load_extend_continue_at_settings(db)
    if not settings.enabled:
        if not _valid_continue_at(request_payload.get("continueAt")):
            raise HTTPException(status_code=400, detail="Automatische continueAt-Analyse ist im Adminbereich deaktiviert und kein gültiger manueller continueAt-Wert vorhanden.")
        return None

    result_payload = _run_auto_continue_at_analysis_for_asset(db, asset)
    request_payload["continueAt"] = result_payload["continue_at"]
    return result_payload


def _get_audio_asset_or_404(asset_id: int, db: Session) -> AudioAsset:
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset or is_bad_image_asset(asset):
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden oder ist kein gültiges AudioAsset.")
    _repair_audio_asset_file_metadata(asset, db)
    attach_audio_asset_identity_context(db, [asset])
    return asset


def _payload_without_empty_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "")}




def _assert_sunoapi_followup_allowed(asset: AudioAsset, action: str) -> None:
    reason = blocked_followup_reason(asset.metadata_json if isinstance(asset.metadata_json, dict) else {}, action)
    if reason:
        raise HTTPException(status_code=400, detail=reason)


def _safe_filename_stem(value: str | None, fallback: str) -> str:
    base = str(value or fallback).strip() or fallback
    base = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", base)
    base = re.sub(r"\s+", "_", base).strip(" ._- ")
    base = re.sub(r"_+", "_", base)
    return (base or fallback)[:110]


def _asset_variant_index(db: Session, asset: AudioAsset) -> int:
    query = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False))
    if asset.project_id:
        query = query.filter(AudioAsset.project_id == asset.project_id)
    elif asset.song_id:
        query = query.filter(AudioAsset.song_id == asset.song_id)
    elif asset.suno_task_id:
        query = query.filter(AudioAsset.suno_task_id == asset.suno_task_id)
    elif asset.task_local_id:
        query = query.filter(AudioAsset.task_local_id == asset.task_local_id)
    else:
        return 1
    rows = [row for row in query.order_by(AudioAsset.created_at.asc(), AudioAsset.id.asc()).all() if not is_bad_image_asset(row)]
    for index, row in enumerate(rows, start=1):
        if row.id == asset.id:
            return index
    return 1


def _safe_download_filename(asset: AudioAsset, path: Path, db: Session) -> str:
    title = asset.display_title or asset.title or f"audio_{asset.id}"
    extension = path.suffix.lower() or ".mp3"
    base = _safe_filename_stem(title, f"audio_{asset.id}")
    variant = _asset_variant_index(db, asset)
    # Suno-ähnlicher Variantenname: Donnerbalken_4_1.mp3, Donnerbalken_4_2.mp3
    return f"{base}_{variant}{extension}"

def _is_public_http_url(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    if host.endswith(".local") or host.startswith("192.168.") or host.startswith("10."):
        return False
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return False
        except Exception:
            pass
    return True


def _extract_uploaded_download_url(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = []
    for key in ("downloadUrl", "download_url", "url", "fileUrl", "file_url"):
        candidates.append(payload.get(key))
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("downloadUrl", "download_url", "url", "fileUrl", "file_url"):
            candidates.append(data.get(key))
    elif isinstance(data, str):
        candidates.append(data)
    for value in candidates:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _get_reusable_audio_url(asset: AudioAsset) -> str:
    for value in (asset.source_url, asset.public_url):
        if _is_public_http_url(value):
            return str(value)
    raise HTTPException(status_code=400, detail="Für diese Audio-Datei ist keine öffentliche wiederverwendbare Audio-URL gespeichert.")


async def _get_reusable_upload_url(asset: AudioAsset, db: Session) -> str:
    for value in (asset.source_url, asset.public_url):
        if _is_public_http_url(value):
            return str(value)

    path = _local_audio_path_or_404(asset, db)
    content_type = _normalized_audio_content_type(asset.content_type, path) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    try:
        result = await SunoAPIClient().upload_stream(path.name, path.read_bytes(), content_type)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Temporärer SunoAPI-Dateiupload fehlgeschlagen: {exc}") from exc

    uploaded_url = _extract_uploaded_download_url(result)
    if not uploaded_url:
        raise HTTPException(status_code=502, detail=f"SunoAPI-Dateiupload lieferte keine downloadUrl: {result}")

    metadata = dict(asset.metadata_json or {})
    uploads = list(metadata.get("suno_temp_uploads") or [])
    uploads.append({
        "download_url": uploaded_url,
        "filename": path.name,
        "content_type": content_type,
        "created_at": utc_now_naive().isoformat(),
        "note": "Temporärer Upload für SunoAPI Upload-/Cover-/Add-Operationen. Laut SunoAPI nur zeitlich begrenzt verfügbar.",
    })
    metadata["suno_temp_uploads"] = uploads[-10:]
    asset.metadata_json = metadata
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return uploaded_url




def _save_temp_cover_reference(upload: UploadFile | None, asset: AudioAsset) -> str | None:
    if not upload or not upload.filename:
        return None
    settings = get_settings()
    extension = Path(upload.filename).suffix.lower()
    if extension not in settings.cover_allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Nicht erlaubtes Referenzbild-Format: {extension or 'unbekannt'}")
    content_type = (upload.content_type or '').lower()
    if content_type and content_type not in settings.cover_allowed_content_types_list:
        raise HTTPException(status_code=400, detail=f"Nicht erlaubter Referenzbild-Typ: {content_type}")
    temp_dir = settings.cover_storage_path / '_tmp_refs'
    temp_dir.mkdir(parents=True, exist_ok=True)
    target = temp_dir / f"cover_ref_{asset.id}_{utc_now_naive().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
    total = 0
    with target.open('wb') as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.cover_max_download_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=f"Referenzbild überschreitet {settings.suno_cover_max_download_mb} MB.")
            handle.write(chunk)
    return str(target)


def _metadata_dict(value: dict | None) -> dict:
    return value if isinstance(value, dict) else {}


def _metadata_source_url(metadata: dict | None, *keys: str) -> str | None:
    meta = _metadata_dict(metadata)
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    cover_cache = meta.get('cover_cache') if isinstance(meta.get('cover_cache'), dict) else {}
    generated_cover = meta.get('generated_cover') if isinstance(meta.get('generated_cover'), dict) else {}
    for source in (cover_cache, generated_cover):
        for key in ('replicate_source_url', 'source_url', 'remote_url'):
            value = source.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def _local_cover_exists(value: str | None) -> bool:
    if not value:
        return False
    settings = get_settings()
    route = settings.suno_cover_public_route.rstrip('/') + '/'
    text = str(value)
    candidates: list[Path] = []
    if text.startswith(route):
        candidates.append(settings.cover_storage_path / text.rsplit('/', 1)[-1])
    candidate = Path(text)
    candidates.append(candidate)
    if candidate.name:
        candidates.append(settings.cover_storage_path / candidate.name)
    return any(path.exists() and path.is_file() and path.stat().st_size > 0 for path in candidates)


def _audio_file_exists(asset: AudioAsset) -> bool:
    if repair_local_file_metadata(asset):
        return True
    for value in (asset.local_path, asset.filename):
        if not value:
            continue
        path = Path(str(value))
        candidates = [path, get_settings().audio_storage_path / path.name]
        if any(candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0 for candidate in candidates):
            return True
    return False



def _normalized_audio_content_type(content_type: str | None, path: Path) -> str:
    return normalize_audio_content_type(content_type, path)


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


def _resolve_local_audio_path(asset: AudioAsset) -> Path | None:
    settings = get_settings()
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

    # Wichtig für alte Datenbankstände: ältere Versionen haben Dateien als
    # audio_<DB-ID>_<Hash>.mp3 gespeichert, ohne filename/local_path sauber zu aktualisieren.
    if storage_path.exists():
        for extension in settings.audio_allowed_extensions_list:
            candidates.extend(sorted(storage_path.glob(f"audio_{asset.id}_*{extension}")))
        # Nicht breit mit *{id}_* suchen: Asset-ID 10 würde sonst z.B. audio_103_*
        # treffen und damit einen fremden Song streamen. Nur alte Dateien mit
        # klar getrenntem _<id>_-Segment sind zulässig.
        candidates.extend(sorted(storage_path.glob(f"*_{asset.id}_*.mp3")))

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


def _repair_audio_asset_file_metadata(asset: AudioAsset, db: Session) -> None:
    if is_bad_image_asset(asset):
        if not asset.is_deleted:
            asset.is_deleted = True
            asset.deleted_reason = "Bereinigt: Bild-URL wurde fälschlich als Audio gespeichert."
            db.add(asset)
            db.commit()
        return

    changed = repair_local_file_metadata(asset)
    if changed:
        db.add(asset)
        db.commit()
        db.refresh(asset)


def _local_audio_path_or_404(asset: AudioAsset, db: Session | None = None) -> Path:
    if asset.status != "cached" and not asset.local_path and not asset.filename and not asset.public_url:
        raise HTTPException(status_code=404, detail="Audio-Datei ist nicht lokal gespeichert.")

    path = _resolve_local_audio_path(asset)
    if not path:
        raise HTTPException(status_code=404, detail="Lokale Audio-Datei fehlt auf dem Server oder der gespeicherte Pfad ist veraltet.")

    if db is not None:
        _repair_audio_asset_file_metadata(asset, db)

    return path


def _get_reusable_audio_id(asset: AudioAsset) -> str:
    if asset.audio_id:
        return asset.audio_id
    raise HTTPException(
        status_code=400,
        detail="Für diese Audio-Datei ist keine Suno Audio-ID gespeichert. Bitte Task erneut aktualisieren oder eine neuere Generierung verwenden.",
    )


def _get_reusable_task_id(asset: AudioAsset) -> str:
    if asset.suno_task_id:
        return asset.suno_task_id
    raise HTTPException(
        status_code=400,
        detail="Für diese Audio-Datei ist keine Suno Task-ID gespeichert. Bitte Task erneut aktualisieren oder eine neuere Generierung verwenden.",
    )




def _is_external_cover_url(value: str | None) -> bool:
    if not value:
        return False
    text = str(value).strip()
    return text.startswith("http://") or text.startswith("https://")


@router.post("/covers/cache-missing", response_model=dict)
async def cache_missing_covers(limit: int = 500, db: Session = Depends(get_db)):
    service = CoverCacheService(db)
    cached_assets = 0
    cached_songs = 0
    failed = 0

    assets = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.updated_at.desc())
        .limit(limit)
        .all()
    )
    for asset in assets:
        if not _is_external_cover_url(asset.image_url):
            continue
        try:
            result = await service.cache_asset_cover(asset)
            if result:
                cached_assets += 1
        except Exception:
            failed += 1

    songs = (
        db.query(Song)
        .filter(Song.is_deleted.is_(False))
        .order_by(Song.updated_at.desc())
        .limit(limit)
        .all()
    )
    for song in songs:
        if not _is_external_cover_url(song.cover_image_url):
            continue
        try:
            result = await service.cache_song_cover(song)
            if result:
                cached_songs += 1
        except Exception:
            failed += 1

    return {
        "ok": True,
        "cached_assets": cached_assets,
        "cached_songs": cached_songs,
        "failed": failed,
        "message": f"Cover gesichert: {cached_assets} AudioAssets, {cached_songs} Songs, {failed} Fehler",
    }


@router.post("/content/cache-missing", response_model=dict)
async def cache_missing_library_content(limit: int = 5000, db: Session = Depends(get_db)):
    return await cache_missing_library_content_once(db, limit=limit, notify_always=True, background=False)


@router.get("/audio", response_model=list[AudioAssetRead])
def list_audio_assets(db: Session = Depends(get_db)):
    # Read-only: Die Library liest ausschließlich die zentrale Tabelle audio_assets.
    # Task-Ergebnisse müssen im Task-Success-Pfad materialisiert werden; der
    # Listenpfad darf keine schweren Reparaturen oder Schreibzugriffe auslösen.
    return active_usable_audio_assets(db, limit=500)


@router.post("/audio/materialize-from-tasks", response_model=dict)
def materialize_audio_assets_from_recent_tasks(limit: int = 80, db: Session = Depends(get_db)):
    # Diagnose-/Notfall-Endpunkt. Der normale Root-Fix läuft im Task-Success-Pfad
    # über MusicService.refresh_task(); dieser Endpoint ist nur für Altbestände
    # und manuelle Wartung gedacht.
    result = AudioAssetMaterializationService(db).materialize_recent_tasks(limit=limit, force=True)
    return {"ok": True, **result.as_payload()}


@router.get("/audio/{asset_id}", response_model=AudioAssetRead)
def get_audio_asset(asset_id: int, db: Session = Depends(get_db)):
    return _get_audio_asset_or_404(asset_id, db)


@router.get("/audio/{asset_id}/timestamped-lyrics", response_model=dict)
def get_saved_timestamped_lyrics(asset_id: int, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return {
        "ok": True,
        "asset_id": asset.id,
        "audio_id": asset.audio_id,
        "task_id": asset.suno_task_id,
        "timestamped_lyrics": metadata.get("timestamped_lyrics"),
        "timestamped_lyrics_fetched_at": metadata.get("timestamped_lyrics_fetched_at"),
    }


@router.post("/audio/{asset_id}/timestamped-lyrics", response_model=dict)
async def fetch_and_save_timestamped_lyrics(asset_id: int, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    audio_id = _get_reusable_audio_id(asset)
    payload: dict[str, Any] = {"audio_id": audio_id}
    if asset.suno_task_id:
        payload["task_id"] = asset.suno_task_id

    try:
        result = await SunoAPIClient().get_timestamped_lyrics(payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    metadata = dict(asset.metadata_json or {})
    metadata["timestamped_lyrics"] = result
    metadata["timestamped_lyrics_fetched_at"] = utc_now_naive().isoformat()
    metadata["timestamped_lyrics_request"] = payload
    asset.metadata_json = metadata
    db.add(asset)
    db.commit()
    db.refresh(asset)

    return {
        "ok": True,
        "asset_id": asset.id,
        "audio_id": asset.audio_id,
        "task_id": asset.suno_task_id,
        "timestamped_lyrics": result,
        "timestamped_lyrics_fetched_at": metadata["timestamped_lyrics_fetched_at"],
    }




@router.post("/audio/{asset_id}/prepare-playback")
async def prepare_audio_asset_playback(asset_id: int, db: Session = Depends(get_db)):
    """Bereitet eine konkrete AudioAsset-Variante für sofortige Wiedergabe vor.

    Der Player ruft diesen Endpunkt vor bzw. nach einem fehlgeschlagenen Play-Versuch auf.
    Damit wird ein kurz zuvor materialisiertes Remote-Asset bei aktivem lokalem Storage
    gezielt nachgeladen, ohne einen globalen Library-Repair oder breiten Storage-Scan
    auszulösen. Der Endpunkt arbeitet ausschließlich asset-zentriert.
    """
    asset = _get_audio_asset_or_404(asset_id, db)
    path = _resolve_local_audio_path(asset)
    if path:
        _repair_audio_asset_file_metadata(asset, db)
        return {
            "ok": True,
            "audio_asset_id": asset.id,
            "ready": True,
            "cached": True,
            "status": asset.status or "cached",
            "stream_url": f"/api/archive/audio/{asset.id}/stream",
            "message": "Lokale Audiodatei ist abspielbereit.",
        }

    settings = get_settings()
    if not getattr(settings, "local_content_storage_enabled", True) or settings.suno_audio_cache_mode.strip().lower() == "off":
        return {
            "ok": True,
            "audio_asset_id": asset.id,
            "ready": bool(_is_public_http_url(asset.source_url)),
            "cached": False,
            "status": asset.status or "remote",
            "stream_url": f"/api/archive/audio/{asset.id}/stream",
            "message": "Lokaler Cache ist deaktiviert; Wiedergabe nutzt Remote-Quelle.",
        }

    if not _is_public_http_url(asset.source_url):
        return {
            "ok": False,
            "audio_asset_id": asset.id,
            "ready": False,
            "cached": False,
            "status": asset.status or "remote",
            "stream_url": f"/api/archive/audio/{asset.id}/stream",
            "message": "Keine direkt cachebare Audio-Quelle vorhanden.",
        }

    candidate = AudioCandidate(
        source_url=asset.source_url,
        audio_id=asset.audio_id,
        title=asset.display_title or asset.title,
        image_url=asset.image_url,
        duration_seconds=asset.duration_seconds,
        metadata={
            "source": "prepare_playback",
            "audio_asset_id": asset.id,
        },
    )

    try:
        prepared = await AudioCacheService(db).cache_asset_from_candidate(asset, candidate)
        path = _resolve_local_audio_path(prepared)
        return {
            "ok": True,
            "audio_asset_id": prepared.id,
            "ready": bool(path),
            "cached": bool(path),
            "status": prepared.status or ("cached" if path else "remote"),
            "stream_url": f"/api/archive/audio/{prepared.id}/stream",
            "message": "Audiodatei wurde für die Wiedergabe lokal vorbereitet." if path else "AudioAsset wurde geprüft, aber keine lokale Datei gefunden.",
        }
    except Exception as exc:
        asset.status = asset.status or "remote"
        asset.error_message = f"Playback-Prepare-Fehler: {exc}"
        db.add(asset)
        db.commit()
        return {
            "ok": False,
            "audio_asset_id": asset.id,
            "ready": bool(_is_public_http_url(asset.source_url)),
            "cached": False,
            "status": asset.status or "remote",
            "stream_url": f"/api/archive/audio/{asset.id}/stream",
            "message": f"Lokale Vorbereitung fehlgeschlagen: {exc}",
        }

@router.get("/audio/{asset_id}/stream")
def stream_audio_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    if not _audio_file_exists(asset) and _is_public_http_url(asset.source_url):
        return RedirectResponse(asset.source_url, status_code=307)
    path = _local_audio_path_or_404(asset, db)
    file_size = path.stat().st_size
    if file_size <= 0:
        raise HTTPException(status_code=404, detail="Lokale Audio-Datei ist leer.")

    media_type = _normalized_audio_content_type(asset.content_type, path)
    range_header = request.headers.get("range")
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f'inline; filename="{asset.filename or path.name}"',
        "X-Audio-Asset-Id": str(asset.id),
        "X-Song-Id": str(asset.song_id or ""),
        "X-Suno-Task-Id": str(asset.suno_task_id or ""),
        "X-Suno-Audio-Id": str(asset.audio_id or ""),
    }

    if range_header:
        try:
            unit, requested_range = range_header.strip().split("=", 1)
            if unit.lower() != "bytes":
                raise ValueError("Unsupported range unit")
            start_text, end_text = requested_range.split("-", 1)
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
        headers = {
            **base_headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(content_length),
        }
        return StreamingResponse(
            _iter_file_range(path, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers = {**base_headers, "Content-Length": str(file_size)}
    return StreamingResponse(
        _iter_file_range(path, 0, file_size - 1),
        media_type=media_type,
        headers=headers,
    )


@router.get("/audio/{asset_id}/waveform", response_model=AudioWaveformRead)
def get_audio_waveform(asset_id: int, response: Response, points: int = 180, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    asset = _get_audio_asset_or_404(asset_id, db)
    path = _local_audio_path_or_404(asset, db)
    payload = get_or_create_waveform(asset, path, db, points=points, rebuild=False)
    return sanitize_waveform_payload_for_asset(asset, payload) or payload


@router.post("/audio/{asset_id}/waveform/rebuild", response_model=AudioWaveformRead)
def rebuild_audio_waveform(asset_id: int, response: Response, points: int = 180, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    asset = _get_audio_asset_or_404(asset_id, db)
    path = _local_audio_path_or_404(asset, db)
    payload = get_or_create_waveform(asset, path, db, points=points, rebuild=True)
    return sanitize_waveform_payload_for_asset(asset, payload) or payload


@router.get("/audio/{asset_id}/download")
def download_audio_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    if not _audio_file_exists(asset) and _is_public_http_url(asset.source_url):
        return RedirectResponse(asset.source_url, status_code=307)
    path = _local_audio_path_or_404(asset, db)
    return FileResponse(
        path,
        media_type=_normalized_audio_content_type(asset.content_type, path),
        filename=_safe_download_filename(asset, path, db),
    )


@router.post("/audio/{asset_id}/extend", response_model=TaskRead)
async def extend_from_audio_asset(asset_id: int, payload: ArchiveAudioExtendRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "extend_music")
    request_payload = _payload_without_empty_values(payload.model_dump(by_alias=True, exclude_none=True))
    _apply_auto_continue_at_for_archive_extend(db, asset, request_payload)
    request_payload["audioId"] = _get_reusable_audio_id(asset)
    if not request_payload.get("title") and asset.title:
        request_payload["title"] = f"{asset.title} Extended"
    try:
        return await MusicService(db).call_task_endpoint("extend_music", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/extend/analyze-continue-at", response_model=dict)
def analyze_extend_continue_at(asset_id: int, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "extend_music")
    return _run_auto_continue_at_analysis_for_asset(db, asset)


@router.post("/audio/{asset_id}/cover-song", response_model=TaskRead)
async def cover_song_from_audio_asset(asset_id: int, payload: ArchiveAudioCoverSongRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "upload_and_cover")
    request_payload = _payload_without_empty_values(payload.model_dump(by_alias=True, exclude_none=True))
    request_payload["uploadUrl"] = await _get_reusable_upload_url(asset, db)
    if not request_payload.get("title") and asset.title:
        request_payload["title"] = f"{asset.title} Cover"
    try:
        return await MusicService(db).call_task_endpoint("upload_and_cover", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/add-vocals", response_model=TaskRead)
async def add_vocals_from_audio_asset(asset_id: int, payload: ArchiveAudioAddVocalsRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "add_vocals")
    request_payload = _payload_without_empty_values(payload.model_dump(by_alias=True, exclude_none=True))
    request_payload["uploadUrl"] = await _get_reusable_upload_url(asset, db)
    try:
        return await MusicService(db).call_task_endpoint("add_vocals", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/add-instrumental", response_model=TaskRead)
async def add_instrumental_from_audio_asset(asset_id: int, payload: ArchiveAudioAddInstrumentalRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "add_instrumental")
    request_payload = _payload_without_empty_values(payload.model_dump(by_alias=True, exclude_none=True))
    request_payload["uploadUrl"] = await _get_reusable_upload_url(asset, db)
    try:
        return await MusicService(db).call_task_endpoint("add_instrumental", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/create-persona", response_model=TaskRead)
async def create_persona_from_audio_asset(asset_id: int, payload: ArchiveAudioPersonaRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "generate_persona")
    request_payload = _payload_without_empty_values(payload.model_dump(exclude_none=True))
    request_payload["task_id"] = _get_reusable_task_id(asset)
    request_payload["audio_id"] = _get_reusable_audio_id(asset)
    try:
        return await MusicService(db).call_task_endpoint("generate_persona", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/create-cover-image", response_model=TaskRead)
async def create_cover_image_from_audio_asset(asset_id: int, payload: ArchiveAudioCoverImageRequest, db: Session = Depends(get_db)):
    asset = _get_audio_asset_or_404(asset_id, db)
    _assert_sunoapi_followup_allowed(asset, "create_cover")
    request_payload = _payload_without_empty_values(payload.model_dump(exclude_none=True))
    request_payload["task_id"] = _get_reusable_task_id(asset)
    try:
        return await MusicService(db).call_task_endpoint("create_cover", request_payload)
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/audio/{asset_id}/generate-ai-cover", response_model=TaskRead)
async def generate_ai_cover_from_audio_asset(
    asset_id: int,
    background_tasks: BackgroundTasks,
    model: str = Form(default="pro"),
    note: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    asset = _get_audio_asset_or_404(asset_id, db)
    model = str(model or 'pro').strip().lower()
    if model not in REPLICATE_COVER_MODELS:
        raise HTTPException(status_code=400, detail=f"Ungültiges Cover-Modell: {model}")
    reference_path = _save_temp_cover_reference(reference_image, asset) if reference_image else None
    task = ReplicateCoverService(db).create_status_task(asset, model=model, note=note, has_reference=bool(reference_path))
    background_tasks.add_task(ReplicateCoverService.run_generation_task, task.id, asset.id, model, note, reference_path)
    return task
