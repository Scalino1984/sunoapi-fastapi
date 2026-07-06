"""Music API routes.

Wichtig fuer /api/music/generate: GenerateMusicRequest wird mit by_alias=True
serialisiert, damit request_payload die offiziellen SunoAPI-Felder
negativeTags/vocalGender enthaelt. Nicht auf exclude_none-only ohne Alias
zurueckbauen, sonst verschwinden die angezeigten Optionen aus DB/Library.
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import ActivityLog, AudioAsset, Persona, Song, StatusNotification, SunoTask, VideoAsset
from app.schemas import (
    AddInstrumentalRequest,
    AddVocalsRequest,
    BoostMusicStyleRequest,
    CreateVideoRequest,
    GenerateMashupRequest,
    GenerateSoundsRequest,
    ImportSunoTaskRequest,
    ImportSunoSongRequest,
    ImportSunoSongResponse,
    BatchImportSunoTaskRequest,
    BatchImportSunoSongRequest,
    SunoSafeCheckRequest,
    ExtendMusicRequest,
    GenerateMusicRequest,
    GenerateCoverRequest,
    GeneratePersonaRequest,
    ReplaceSectionRequest,
    GenericAudioUrlRequest,
    PersonaRead,
    SongRead,
    VoiceCreate,
    VoiceRead,
    VoiceUpdate,
    VoiceValidateRequest,
    VoiceRegenerateRequest,
    CustomVoiceRequest,
    VoiceAvailabilityRequest,
    TaskRead,
    UploadAndCoverRequest,
    UploadAndExtendRequest,
)
from app.services.music_service import MusicService
from app.services.extend_continue_at_analysis_service import analyze_continue_at_for_audio_url, load_extend_continue_at_settings
from app.services.suno_song_import_service import SunoSongImportService
from app.services.song_library_sync_service import SongLibrarySyncService
from app.services.system_status_notification_service import create_system_status_notification
from app.services.background_task_runner import run_detached_process
from app.services.task_lifecycle_service import (
    append_task_debug_event,
    append_task_step_log,
    heartbeat_task,
    is_cancel_requested,
    mark_task_finished,
    mark_task_started,
    request_task_cancel,
    start_task_heartbeat,
)
from app.services.opencli_provider_service import OpenCliProviderError, OpenCliProviderService, run_opencli_generation_background
from app.suno_client import SunoAPIClient, SunoAPIError
from app.routers.audio_assets import (
    _create_bulk_status_task,
    _run_bulk_srt_generation_background,
    _run_bulk_stems_generation_background,
)
from app.utils.time_utils import utc_now_naive


router = APIRouter(prefix="/api/music", tags=["music"])


SENSITIVE_HEURISTIC_WORDS = [
    "fick", "ficken", "ficker", "sex", "porno", "nutte", "hure", "wichs", "vergewalt", "mutterf",
    "kill", "töten", "tod", "bombe", "terror", "waffe", "blut", "messer", "droge", "weed", "kokain",
]


def _dedupe_ints(values: list[int | None]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            item = int(value) if value is not None else 0
        except (TypeError, ValueError):
            continue
        if item <= 0 or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result


def _collect_imported_audio_asset_ids(db: Session, *, task: SunoTask | None = None, result: dict | None = None) -> list[int]:
    values: list[int | None] = []
    if isinstance(result, dict):
        values.append(result.get("audio_asset_id"))
    if task:
        if task.id:
            values.extend([row.id for row in db.query(AudioAsset.id).filter(AudioAsset.task_local_id == task.id, AudioAsset.is_deleted.is_(False)).all()])
        if task.task_id:
            values.extend([row.id for row in db.query(AudioAsset.id).filter(AudioAsset.suno_task_id == task.task_id, AudioAsset.is_deleted.is_(False)).all()])
            song_ids = [row.id for row in db.query(Song.id).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).all()]
            if song_ids:
                values.extend([row.id for row in db.query(AudioAsset.id).filter(AudioAsset.song_id.in_(song_ids), AudioAsset.is_deleted.is_(False)).all()])
    return _dedupe_ints(values)



def _collect_imported_video_asset_ids(db: Session, *, task: SunoTask | None = None) -> list[int]:
    # /imports-MP4-Vertrag: Videos werden als video_assets an AudioAssets gebunden.
    # Batch-Status darf sie nicht als AudioAssets zaehlen, muss sie aber sichtbar machen.
    values: list[int | None] = []
    if task:
        attached_video_id = getattr(task, "import_video_asset_id", None)
        if attached_video_id:
            values.append(attached_video_id)
        if task.id:
            values.extend([row.id for row in db.query(VideoAsset.id).filter(VideoAsset.task_local_id == task.id, VideoAsset.is_deleted.is_(False)).all()])
        if task.task_id:
            values.extend([row.id for row in db.query(VideoAsset.id).filter(VideoAsset.suno_task_id == task.task_id, VideoAsset.is_deleted.is_(False)).all()])
    return _dedupe_ints(values)



def _create_import_status_task(db: Session, *, task_type: str, title: str, message: str, request_payload: dict | None = None) -> SunoTask:
    """Create a visible RUNNING master task for import jobs before work starts."""
    task = SunoTask(
        task_id=None,
        task_type=task_type,
        status="RUNNING",
        request_payload={"background": True, "local_task": True, **(request_payload or {})},
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
        content_type="task_status",
        content_id=task.id,
        target_tab="status",
        target_payload={"task_local_id": task.id, "task_type": task_type, "status": "RUNNING"},
    ))
    db.commit()
    return task


def _finish_import_status_task(
    db: Session,
    task_id: int,
    *,
    task_type: str,
    title: str,
    message: str,
    severity: str,
    summary: dict,
    imported: list[dict],
    already_imported: list[dict],
    failed: list[dict],
    post_actions: list[dict],
) -> None:
    now = utc_now_naive()
    status = "SUCCESS" if not failed else ("PARTIAL_SUCCESS" if imported or already_imported else "FAILED")
    task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
    if task:
        task.status = status
        task.completed_at = now
        task.heartbeat_at = now
        task.error_message = None if not failed else message
        task.result_payload = {
            "status": status,
            "summary": summary,
            "imported": imported,
            "already_imported": already_imported,
            "failed": failed,
            "post_actions": post_actions,
            "completed_at": now.isoformat(),
        }
        task.response_payload = {**(task.response_payload or {}), "status": status, "completed_at": now.isoformat()}
        final_phase = "completed" if status == "SUCCESS" else ("partial_success" if status == "PARTIAL_SUCCESS" else "failed")
        append_task_debug_event(
            db,
            task,
            event="import_status_finished",
            detail=message,
            level="info" if status == "SUCCESS" else ("warning" if status == "PARTIAL_SUCCESS" else "error"),
            data={
                "task_type": task_type,
                "status": status,
                "summary": summary,
                "imported_count": len(imported),
                "already_imported_count": len(already_imported),
                "failed_count": len(failed),
                "post_actions_count": len(post_actions),
                "failed_preview": failed[:10],
            },
            commit=False,
        )
        append_task_step_log(
            db,
            task,
            phase=final_phase,
            phase_label="Import abgeschlossen" if status == "SUCCESS" else ("Import teilweise abgeschlossen" if status == "PARTIAL_SUCCESS" else "Import fehlgeschlagen"),
            detail=message,
            data={"task_type": task_type, "status": status, "summary": summary},
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
        event_type=f"{task_type}_completed" if status == "SUCCESS" else f"{task_type}_finished_with_errors",
        title=title,
        message=message,
        severity=severity,
        status="unread",
        task_local_id=task_id,
        suno_task_id=None,
        content_type="task_status",
        content_id=task_id,
        target_tab="status",
        target_payload={
            "task_local_id": task_id,
            "task_type": task_type,
            "status": status,
            "summary": summary,
            "post_actions": post_actions,
            "imported": imported[:10],
            "already_imported": already_imported[:10],
            "failed": failed[:10],
        },
        completed_at=now,
    ))
    db.commit()


async def _run_post_import_audio_actions_inline(db: Session, *, asset_ids: list[int], generate_srt: bool = False, generate_stems: bool = False) -> list[dict]:
    """Create visible child tasks and execute post-import jobs in this background worker."""
    asset_ids = _dedupe_ints(asset_ids)
    actions: list[dict] = []
    if not asset_ids:
        return actions
    if generate_stems:
        task = _create_bulk_status_task(
            db,
            task_type="bulk_generate_stems",
            title="Stem-Erzeugung nach Import gestartet",
            message=f"Stem-Erzeugung für {len(asset_ids)} importierte Variante(n) läuft im Hintergrund.",
            asset_ids=asset_ids,
            request_payload={"source": "post_import", "generate_stems": True},
        )
        actions.append({"type": "stems", "task_local_id": task.id, "count": len(asset_ids), "status": "RUNNING"})
        await _run_bulk_stems_generation_background(task.id, {"ids": asset_ids})
    if generate_srt:
        task = _create_bulk_status_task(
            db,
            task_type="bulk_generate_srt",
            title="SRT-Erzeugung nach Import gestartet",
            message=f"SRT-Erzeugung für {len(asset_ids)} importierte Variante(n) läuft im Hintergrund.",
            asset_ids=asset_ids,
            request_payload={"source": "post_import", "force": True, "prefer_existing_vocal_stem": True},
        )
        actions.append({"type": "srt", "task_local_id": task.id, "count": len(asset_ids), "status": "RUNNING"})
        await _run_bulk_srt_generation_background(task.id, {"ids": asset_ids, "force": True, "prefer_existing_vocal_stem": True})
    return actions


async def _run_public_suno_song_batch_import_background(master_task_id: int, payload_data: dict) -> None:
    db = SessionLocal()
    stop_heartbeat = start_task_heartbeat(master_task_id)
    imported: list[dict] = []
    already_imported: list[dict] = []
    failed: list[dict] = []
    all_asset_ids: list[int] = []
    try:
        payload = BatchImportSunoSongRequest(**payload_data)
        timeout_seconds = max(5, int(get_settings().suno_task_import_item_timeout_seconds))
        total = len(payload.parsed_song_ids)
        for index, song_ref in enumerate(payload.parsed_song_ids, start=1):
            heartbeat_task(db, master_task_id, progress={"current": index, "total": total, "input": song_ref, "processed": len(imported) + len(already_imported) + len(failed)})
            if is_cancel_requested(db, master_task_id):
                failed.append({"input": song_ref, "error": "Batch-Import wurde manuell abgebrochen."})
                break
            try:
                item_db = SessionLocal()
                try:
                    item_service = SunoSongImportService(item_db)
                    result = await asyncio.wait_for(item_service.import_song({
                        "song_id": song_ref,
                        "cache_audio": payload.cache_audio,
                        "cache_cover": payload.cache_cover,
                        "import_video_url": payload.import_video_url,
                        "overwrite_existing": payload.overwrite_existing,
                    }), timeout=timeout_seconds)
                    asset_ids = _collect_imported_audio_asset_ids(item_db, result=result)
                    row = {
                        "input": song_ref,
                        "suno_song_id": result.get("suno_song_id"),
                        "song_id": result.get("song_id"),
                        "audio_asset_id": result.get("audio_asset_id"),
                        "audio_asset_ids": asset_ids,
                        "task_local_id": result.get("task_local_id"),
                        "already_imported": bool(result.get("already_imported")),
                        "message": result.get("message"),
                    }
                finally:
                    item_db.close()
                all_asset_ids.extend(asset_ids)
                if result.get("already_imported"):
                    already_imported.append(row)
                else:
                    imported.append(row)
            except Exception as exc:
                failed.append({"input": song_ref, "error": getattr(exc, "detail", str(exc))})
        post_actions = await _run_post_import_audio_actions_inline(
            db,
            asset_ids=all_asset_ids,
            generate_srt=bool(payload.generate_srt),
            generate_stems=bool(payload.generate_stems),
        )
        message = f"{len(imported)} importiert, {len(already_imported)} bereits vorhanden, {len(failed)} Fehler."
        if post_actions:
            message += " Zusatzaufgaben gestartet: " + ", ".join(action["type"].upper() for action in post_actions) + "."
        summary = {
            "total": len(payload.parsed_song_ids),
            "imported": len(imported),
            "already_imported": len(already_imported),
            "failed": len(failed),
            "post_action_assets": len(_dedupe_ints(all_asset_ids)),
        }
        _finish_import_status_task(
            db,
            master_task_id,
            task_type="import_suno_song_batch",
            title="Suno.com Song-Batchimport abgeschlossen",
            message=message,
            severity=_batch_import_severity(imported, already_imported, failed),
            summary=summary,
            imported=imported,
            already_imported=already_imported,
            failed=failed,
            post_actions=post_actions,
        )
    except Exception as exc:
        _finish_import_status_task(
            db,
            master_task_id,
            task_type="import_suno_song_batch",
            title="Suno.com Song-Batchimport fehlgeschlagen",
            message=str(exc),
            severity="error",
            summary={"total": 0, "imported": 0, "already_imported": 0, "failed": 1, "post_action_assets": 0},
            imported=imported,
            already_imported=already_imported,
            failed=failed or [{"error": str(exc)}],
            post_actions=[],
        )
    finally:
        stop_heartbeat()
        db.close()


async def _run_sunoapi_task_batch_import_background(master_task_id: int, payload_data: dict) -> None:
    db = SessionLocal()
    stop_heartbeat = start_task_heartbeat(master_task_id)
    imported: list[dict] = []
    already_imported: list[dict] = []
    failed: list[dict] = []
    all_asset_ids: list[int] = []
    all_video_ids: list[int] = []
    try:
        payload = BatchImportSunoTaskRequest(**payload_data)
        timeout_seconds = max(5, int(get_settings().suno_task_import_item_timeout_seconds))
        total = len(payload.parsed_task_ids)
        for index, task_id in enumerate(payload.parsed_task_ids, start=1):
            heartbeat_task(db, master_task_id, progress={"current": index, "total": total, "task_id": task_id, "processed": len(imported) + len(already_imported) + len(failed)})
            if is_cancel_requested(db, master_task_id):
                failed.append({"task_id": task_id, "error": "Batch-Import wurde manuell abgebrochen."})
                break
            try:
                title = f"{payload.title_prefix} {index}" if payload.title_prefix else None
                item_db = SessionLocal()
                try:
                    item_service = MusicService(item_db)
                    result = await asyncio.wait_for(item_service.import_external_task({
                        "task_id": task_id,
                        "task_type": payload.task_type,
                        "title": title,
                        "cache_audio": payload.cache_audio,
                        "cache_video": payload.cache_video,
                    }), timeout=timeout_seconds)
                    asset_ids = _collect_imported_audio_asset_ids(item_db, task=result)
                    video_ids = _collect_imported_video_asset_ids(item_db, task=result)
                    attached = getattr(result, "__dict__", {})
                    row = {"task_id": task_id, "local_task_id": result.id, "status": result.status, "task_type": result.task_type, "audio_asset_ids": asset_ids, "video_asset_ids": video_ids}
                    was_already_imported = bool(attached.get("already_imported") or attached.get("import_status") == "already_imported")
                finally:
                    item_db.close()
                all_asset_ids.extend(asset_ids)
                all_video_ids.extend(video_ids)
                if was_already_imported:
                    already_imported.append(row)
                else:
                    imported.append(row)
            except Exception as exc:
                failed.append({"task_id": task_id, "error": getattr(exc, "detail", str(exc))})
        post_actions = await _run_post_import_audio_actions_inline(
            db,
            asset_ids=all_asset_ids,
            generate_srt=bool(payload.generate_srt),
            generate_stems=bool(payload.generate_stems),
        )
        message = f"{len(imported)} importiert, {len(already_imported)} bereits vorhanden, {len(failed)} Fehler."
        video_count = len(_dedupe_ints(all_video_ids))
        if video_count:
            message += f" MP4-Videos: {video_count}."
        if post_actions:
            message += " Zusatzaufgaben gestartet: " + ", ".join(action["type"].upper() for action in post_actions) + "."
        summary = {
            "total": len(payload.parsed_task_ids),
            "imported": len(imported),
            "already_imported": len(already_imported),
            "failed": len(failed),
            "post_action_assets": len(_dedupe_ints(all_asset_ids)),
            "video_assets": len(_dedupe_ints(all_video_ids)),
        }
        _finish_import_status_task(
            db,
            master_task_id,
            task_type="import_sunoapi_task_batch",
            title="SunoAPI.org Task-Batchimport abgeschlossen",
            message=message,
            severity=_batch_import_severity(imported, already_imported, failed),
            summary=summary,
            imported=imported,
            already_imported=already_imported,
            failed=failed,
            post_actions=post_actions,
        )
    except Exception as exc:
        _finish_import_status_task(
            db,
            master_task_id,
            task_type="import_sunoapi_task_batch",
            title="SunoAPI.org Task-Batchimport fehlgeschlagen",
            message=str(exc),
            severity="error",
            summary={"total": 0, "imported": 0, "already_imported": 0, "failed": 1, "post_action_assets": 0, "video_assets": 0},
            imported=imported,
            already_imported=already_imported,
            failed=failed or [{"error": str(exc)}],
            post_actions=[],
        )
    finally:
        stop_heartbeat()
        db.close()


def _start_post_import_audio_actions(db: Session, background_tasks: BackgroundTasks, *, asset_ids: list[int], generate_srt: bool = False, generate_stems: bool = False) -> list[dict]:
    asset_ids = _dedupe_ints(asset_ids)
    actions: list[dict] = []
    if not asset_ids:
        return actions
    if generate_stems:
        task = _create_bulk_status_task(
            db,
            task_type="bulk_generate_stems",
            title="Stem-Erzeugung nach Import gestartet",
            message=f"Stem-Erzeugung für {len(asset_ids)} importierte Variante(n) läuft im Hintergrund.",
            asset_ids=asset_ids,
            request_payload={"source": "post_import", "generate_stems": True},
        )
        run_detached_process(f"post-import-stems-{task.id}", _run_bulk_stems_generation_background, task.id, {"ids": asset_ids})
        actions.append({"type": "stems", "task_local_id": task.id, "count": len(asset_ids), "status": "RUNNING"})
    if generate_srt:
        task = _create_bulk_status_task(
            db,
            task_type="bulk_generate_srt",
            title="SRT-Erzeugung nach Import gestartet",
            message=f"SRT-Erzeugung für {len(asset_ids)} importierte Variante(n) läuft im Hintergrund.",
            asset_ids=asset_ids,
            request_payload={"source": "post_import", "force": True, "prefer_existing_vocal_stem": True},
        )
        run_detached_process(f"post-import-srt-{task.id}", _run_bulk_srt_generation_background, task.id, {"ids": asset_ids, "force": True, "prefer_existing_vocal_stem": True})
        actions.append({"type": "srt", "task_local_id": task.id, "count": len(asset_ids), "status": "RUNNING"})
    return actions


def _first_related_task_id(*collections: list[dict]) -> int | None:
    for collection in collections:
        for row in collection or []:
            for key in ("task_local_id", "local_task_id"):
                value = row.get(key) if isinstance(row, dict) else None
                try:
                    if value is not None and int(value) > 0:
                        return int(value)
                except (TypeError, ValueError):
                    continue
    return None


def _batch_import_severity(imported: list[dict], already_imported: list[dict], failed: list[dict]) -> str:
    if failed and not (imported or already_imported):
        return "error"
    if failed:
        return "warning"
    if imported:
        return "success"
    return "info"


def _create_batch_import_notification(
    db: Session,
    *,
    event_type: str,
    title: str,
    message: str,
    summary: dict,
    imported: list[dict],
    already_imported: list[dict],
    failed: list[dict],
    post_actions: list[dict],
    target_task_type: str,
) -> None:
    post_action_task_id = _first_related_task_id(post_actions)
    import_task_id = _first_related_task_id(imported, already_imported)
    target_task_id = post_action_task_id or import_task_id
    target_payload = {
        "task_local_id": target_task_id,
        "task_type": target_task_type,
        "summary": summary,
        "post_actions": post_actions,
        "imported": imported[:10],
        "already_imported": already_imported[:10],
        "failed": failed[:10],
    }
    db.add(StatusNotification(
        event_type=event_type,
        title=title,
        message=message,
        severity=_batch_import_severity(imported, already_imported, failed),
        status="unread",
        task_local_id=target_task_id,
        suno_task_id=None,
        content_type="task_status",
        content_id=target_task_id,
        target_tab="status",
        target_payload=target_payload,
        completed_at=utc_now_naive(),
    ))
    db.commit()


def _safe_check_payload(payload: dict) -> dict:
    prompt = str(payload.get("prompt") or "")
    style = str(payload.get("style") or "")
    negative = str(payload.get("negative_tags") or "")
    haystack = "\n".join([prompt, style, negative]).lower()
    voice_used = bool(str(payload.get("voice_id") or payload.get("persona_id") or "").strip())
    custom_mode = bool(payload.get("customMode") or payload.get("custom_mode"))
    instrumental = bool(payload.get("instrumental"))
    hits = sorted({word for word in SENSITIVE_HEURISTIC_WORDS if word in haystack})
    warnings = []
    actions = []
    score = 0

    if voice_used and not instrumental:
        score += 25
        warnings.append("Voice/Persona ist aktiv. Suno prüft solche Requests erfahrungsgemäß strenger.")
        actions.append({"key": "retry_without_voice", "label": "Ohne Voice erneut versuchen"})
    if custom_mode and not instrumental:
        score += 10
        warnings.append("Custom Mode mit vollständigem Text wird stärker wie Lyrics bewertet.")
    if hits:
        score += min(45, len(hits) * 10)
        warnings.append("Mögliche sensible Begriffe erkannt: " + ", ".join(hits[:12]))
        actions.append({"key": "soften_text", "label": "Text mit KI entschärfen"})
    if len(prompt) > 2800:
        score += 10
        warnings.append("Der Prompt ist sehr lang. Kürzere und sauber getrennte Inhalte sind stabiler.")
    if "pipeline" in haystack or "reimwort" in haystack or "flow-plan" in haystack:
        score += 20
        warnings.append("Der Prompt enthält Analyse-/Pipeline-Begriffe. Diese gehören in den Chat, nicht in den Canvas/Prompt.")
        actions.append({"key": "clean_canvas", "label": "Nur finalen Songtext/Bauplan verwenden"})
    if instrumental and voice_used:
        score += 15
        warnings.append("Instrumental und Voice sind gleichzeitig gesetzt. Für Instrumentals wird Voice ignoriert bzw. sollte entfernt werden.")
        actions.append({"key": "remove_voice", "label": "Voice entfernen"})

    risk = "low"
    if score >= 60:
        risk = "high"
    elif score >= 25:
        risk = "medium"

    cleaned_payload = dict(payload)
    if voice_used:
        for key in ("voice_id", "persona_id", "persona_model", "personaId", "personaModel"):
            cleaned_payload.pop(key, None)
    cleaned_payload["safe_check_applied"] = True

    return {
        "ok": True,
        "risk": risk,
        "score": min(score, 100),
        "warnings": warnings or ["Keine offensichtlichen Risikopunkte erkannt."],
        "actions": actions or [{"key": "generate", "label": "Generierung starten"}],
        "voice_used": voice_used,
        "customMode": custom_mode,
        "instrumental": instrumental,
        "matched_terms": hits,
        "cleaned_payload": cleaned_payload,
    }


@router.get("/runtime-config", response_model=dict)
def get_runtime_config():
    return get_settings().public_runtime_config()


def _valid_continue_at(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _apply_auto_continue_at_for_upload_extend(db: Session, request_payload: dict) -> dict | None:
    auto_requested = bool(request_payload.pop("autoContinueAt", False))
    if not auto_requested:
        return None

    settings = load_extend_continue_at_settings(db)
    if not settings.enabled:
        if not _valid_continue_at(request_payload.get("continueAt")):
            raise HTTPException(status_code=400, detail="Automatische continueAt-Analyse ist im Adminbereich deaktiviert und kein gültiger manueller continueAt-Wert vorhanden.")
        return None

    upload_url = str(request_payload.get("uploadUrl") or request_payload.get("audio_url") or "").strip()
    create_system_status_notification(
        db,
        event_type="extend_continue_at_analysis_started",
        title="Upload-Extend-continueAt-Analyse gestartet",
        message="Die Audio-URL wird für den optimalen Extend-Zeitpunkt analysiert.",
        severity="info",
        target_tab="status",
        target_payload={"status": "RUNNING", "source": "uploadUrl"},
    )
    result = analyze_continue_at_for_audio_url(upload_url, settings)
    request_payload["continueAt"] = result.continue_at
    create_system_status_notification(
        db,
        event_type="extend_continue_at_analysis_completed",
        title="Upload-Extend-continueAt berechnet",
        message=f"Optimierter continueAt-Wert: {result.continue_at:.3f}s ({result.method}).",
        severity="success" if result.confidence >= 0.5 else "warning",
        target_tab="status",
        target_payload={"status": "SUCCESS", "source": "uploadUrl", "analysis": result.to_payload()},
    )
    return result.to_payload()


@router.get("/opencli/status", response_model=dict)
def get_opencli_status(include_account: bool = False, db: Session = Depends(get_db)):
    return OpenCliProviderService(db).runtime_status(include_account=include_account)


@router.post("/generate-opencli", response_model=TaskRead)
async def generate_music_opencli(payload: GenerateMusicRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        task = OpenCliProviderService(db).create_generation_task(payload.model_dump(exclude_none=True))
    except OpenCliProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(run_opencli_generation_background, task.id)
    return task


@router.post("/generate", response_model=TaskRead)
async def generate_music(payload: GenerateMusicRequest, db: Session = Depends(get_db)):
    try:
        return await MusicService(db).generate_music(payload.model_dump(by_alias=True, exclude_none=True))
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/extend", response_model=TaskRead)
async def extend_music(payload: ExtendMusicRequest, db: Session = Depends(get_db)):
    request_payload = payload.model_dump(by_alias=True, exclude_none=True)
    request_payload.pop("autoContinueAt", None)
    if not _valid_continue_at(request_payload.get("continueAt")):
        raise HTTPException(status_code=400, detail="Für direkten Extend ohne AudioAsset ist ein gültiger continueAt-Wert erforderlich.")
    return await MusicService(db).call_task_endpoint("extend_music", request_payload)


@router.post("/upload-and-cover", response_model=TaskRead)
async def upload_and_cover(payload: UploadAndCoverRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("upload_and_cover", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/upload-and-extend", response_model=TaskRead)
async def upload_and_extend(payload: UploadAndExtendRequest, db: Session = Depends(get_db)):
    request_payload = payload.model_dump(by_alias=True, exclude_none=True)
    _apply_auto_continue_at_for_upload_extend(db, request_payload)
    return await MusicService(db).call_task_endpoint("upload_and_extend", request_payload)


@router.post("/add-instrumental", response_model=TaskRead)
async def add_instrumental(payload: AddInstrumentalRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("add_instrumental", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/add-vocals", response_model=TaskRead)
async def add_vocals(payload: AddVocalsRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("add_vocals", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/boost-style", response_model=TaskRead)
async def boost_music_style(payload: BoostMusicStyleRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("boost_music_style", payload.model_dump(exclude_none=True))


@router.post("/mashup", response_model=TaskRead)
async def generate_mashup(payload: GenerateMashupRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("generate_mashup", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/replace-section", response_model=TaskRead)
async def replace_section(payload: ReplaceSectionRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("replace_section", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/persona", response_model=TaskRead)
async def generate_persona(payload: GeneratePersonaRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("generate_persona", payload.model_dump(by_alias=True, exclude_none=True))


@router.get("/personas", response_model=list[PersonaRead])
def list_personas(db: Session = Depends(get_db)):
    return MusicService(db).list_personas()


@router.get("/voices", response_model=list[VoiceRead])
def list_voices(db: Session = Depends(get_db)):
    return MusicService(db).list_voices()


@router.post("/voices", response_model=VoiceRead)
def create_voice(payload: VoiceCreate, db: Session = Depends(get_db)):
    try:
        return MusicService(db).create_voice(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/voices/{local_voice_id}", response_model=VoiceRead)
def update_voice(local_voice_id: int, payload: VoiceUpdate, db: Session = Depends(get_db)):
    try:
        return MusicService(db).update_voice(local_voice_id, payload.model_dump(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/voices/{local_voice_id}", response_model=dict)
def delete_voice(local_voice_id: int, db: Session = Depends(get_db)):
    try:
        return MusicService(db).delete_voice(local_voice_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc




@router.post("/voice/validate", response_model=TaskRead)
async def generate_voice_validation_phrase(payload: VoiceValidateRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("voice_validate", payload.model_dump(exclude_none=True))


@router.get("/voice/validate-info", response_model=dict)
async def get_voice_validation_phrase(task_id: str, db: Session = Depends(get_db)):
    return await MusicService(db).get_voice_validation_phrase(task_id)


@router.post("/voice/regenerate", response_model=TaskRead)
async def regenerate_voice_validation_phrase(payload: VoiceRegenerateRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("voice_regenerate", payload.model_dump(exclude_none=True))


@router.post("/voice/generate", response_model=TaskRead)
async def create_custom_voice(payload: CustomVoiceRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("create_custom_voice", payload.model_dump(exclude_none=True))


@router.get("/voice/record-info", response_model=dict)
async def get_custom_voice_record(task_id: str, db: Session = Depends(get_db)):
    return await MusicService(db).get_custom_voice_record(task_id)


@router.post("/voice/check-availability", response_model=dict)
async def check_voice_availability(payload: VoiceAvailabilityRequest, db: Session = Depends(get_db)):
    return await MusicService(db).check_voice_availability(payload.model_dump(exclude_none=True))


@router.post("/cover", response_model=TaskRead)
async def create_cover(payload: GenerateCoverRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("create_cover", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/sounds", response_model=TaskRead)
async def generate_sounds(payload: GenerateSoundsRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("generate_sounds", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/video", response_model=TaskRead)
async def create_video(payload: CreateVideoRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("create_video", payload.model_dump(by_alias=True, exclude_none=True))




@router.get("/tasks/{local_task_id}", response_model=TaskRead)
def get_task(local_task_id: int, db: Session = Depends(get_db)):
    task = db.query(SunoTask).filter(SunoTask.id == local_task_id, SunoTask.is_deleted.is_(False)).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")
    return task


@router.post("/tasks/{local_task_id}/refresh", response_model=TaskRead)
async def refresh_task(local_task_id: int, db: Session = Depends(get_db)):
    task = db.query(SunoTask).filter(SunoTask.id == local_task_id, SunoTask.is_deleted.is_(False)).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")

    try:
        return await MusicService(db).refresh_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tasks/refresh-pending", response_model=list[TaskRead])
async def refresh_pending_tasks(db: Session = Depends(get_db)):
    return await MusicService(db).refresh_pending_tasks()


@router.post("/songs/import-from-suno", response_model=ImportSunoSongResponse)
async def import_song_from_suno(payload: ImportSunoSongRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        data = payload.model_dump(exclude_none=True)
        result = await SunoSongImportService(db).import_song(data)
        asset_ids = _collect_imported_audio_asset_ids(db, result=result)
        post_actions = _start_post_import_audio_actions(
            db,
            background_tasks,
            asset_ids=asset_ids,
            generate_srt=bool(payload.generate_srt),
            generate_stems=bool(payload.generate_stems),
        )
        result["post_actions"] = post_actions
        if post_actions:
            result["message"] = f"{result.get('message') or 'Suno-Song wurde importiert.'} Zusatzaufgaben gestartet: " + ", ".join(action["type"].upper() for action in post_actions)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/songs/import-from-suno/batch", response_model=dict)
async def import_songs_from_suno_batch(payload: BatchImportSunoSongRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    song_ids = payload.parsed_song_ids
    if not song_ids:
        raise HTTPException(status_code=400, detail="Bitte mindestens eine Suno Song-ID oder URL eintragen.")
    task = _create_import_status_task(
        db,
        task_type="import_suno_song_batch",
        title="Suno.com Song-Batchimport gestartet",
        message=f"Import von {len(song_ids)} öffentlichen Suno.com Song-ID(s)/URL(s) läuft im Hintergrund.",
        request_payload={
            "source": "status_page",
            "import_source": "suno_public_clip",
            "count": len(song_ids),
            "cache_audio": bool(payload.cache_audio),
            "cache_cover": bool(payload.cache_cover),
            "import_video_url": bool(payload.import_video_url),
            "overwrite_existing": bool(payload.overwrite_existing),
            "generate_srt": bool(payload.generate_srt),
            "generate_stems": bool(payload.generate_stems),
        },
    )
    run_detached_process(f"suno-song-batch-import-{task.id}", _run_public_suno_song_batch_import_background, task.id, payload.model_dump())
    return {
        "ok": True,
        "queued": True,
        "task_local_id": task.id,
        "status": "RUNNING",
        "summary": {"total": len(song_ids), "imported": 0, "already_imported": 0, "failed": 0, "post_action_assets": 0},
        "post_actions": [],
        "message": f"Suno.com Song-Batchimport wurde gestartet ({len(song_ids)} Einträge). Status und Ergebnis erscheinen unter Benachrichtigungen & Tasks.",
    }


@router.post("/tasks/import-from-suno", response_model=TaskRead)
async def import_task_from_suno(payload: ImportSunoTaskRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        task = await MusicService(db).import_external_task(payload.model_dump(exclude_none=True))
        asset_ids = _collect_imported_audio_asset_ids(db, task=task)
        post_actions = _start_post_import_audio_actions(
            db,
            background_tasks,
            asset_ids=asset_ids,
            generate_srt=bool(payload.generate_srt),
            generate_stems=bool(payload.generate_stems),
        )
        if post_actions:
            task.result_payload = {**(task.result_payload or {}), "post_import_actions": post_actions}
            db.add(task)
            db.commit()
            db.refresh(task)
        return task
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tasks/import-from-suno/batch", response_model=dict)
async def import_tasks_from_suno_batch(payload: BatchImportSunoTaskRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task_ids = payload.parsed_task_ids
    if not task_ids:
        raise HTTPException(status_code=400, detail="Bitte mindestens eine Task-ID eintragen.")
    task = _create_import_status_task(
        db,
        task_type="import_sunoapi_task_batch",
        title="SunoAPI.org Task-Batchimport gestartet",
        message=f"Import von {len(task_ids)} SunoAPI.org Task-ID(s) läuft im Hintergrund.",
        request_payload={
            "source": "status_page",
            "import_source": "sunoapi_org_task",
            "count": len(task_ids),
            "task_type": payload.task_type,
            "cache_audio": bool(payload.cache_audio),
            "cache_video": bool(payload.cache_video),
            "title_prefix": payload.title_prefix,
            "generate_srt": bool(payload.generate_srt),
            "generate_stems": bool(payload.generate_stems),
        },
    )
    run_detached_process(f"sunoapi-task-batch-import-{task.id}", _run_sunoapi_task_batch_import_background, task.id, payload.model_dump())
    return {
        "ok": True,
        "queued": True,
        "task_local_id": task.id,
        "status": "RUNNING",
        "summary": {"total": len(task_ids), "imported": 0, "already_imported": 0, "failed": 0, "post_action_assets": 0, "video_assets": 0},
        "post_actions": [],
        "message": f"SunoAPI.org Task-Batchimport wurde gestartet ({len(task_ids)} Einträge). Status und Ergebnis erscheinen unter Benachrichtigungen & Tasks.",
    }


@router.post("/safe-check", response_model=dict)
def suno_safe_check(payload: SunoSafeCheckRequest):
    return _safe_check_payload(payload.model_dump(exclude_none=True))


@router.post("/tasks/{local_task_id}/cancel", response_model=TaskRead)
def cancel_task(local_task_id: int, db: Session = Depends(get_db)):
    task = request_task_cancel(db, local_task_id, reason="Manueller Abbruch über Statusseite/API.")
    if not task:
        raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")
    return task


@router.post("/tasks/{local_task_id}/mark-done", response_model=TaskRead)
def mark_task_done(local_task_id: int, db: Session = Depends(get_db)):
    task = db.query(SunoTask).filter(SunoTask.id == local_task_id, SunoTask.is_deleted.is_(False)).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")

    task.status = "COMPLETED_MANUAL"
    task.error_message = None
    task.updated_at = utc_now_naive()
    db.commit()
    db.refresh(task)
    return task


@router.delete("/history", response_model=dict)
def clear_history(db: Session = Depends(get_db)):
    deleted_at = utc_now_naive()
    counters = {"audio_assets": 0, "tasks": 0, "personas": 0, "songs": 0}
    for model, key, content_type in (
        (AudioAsset, "audio_assets", "audio"),
        (SunoTask, "tasks", "task"),
        (Persona, "personas", "persona"),
        (Song, "songs", "song"),
    ):
        for item in db.query(model).filter(model.is_deleted.is_(False)).all():
            item.is_deleted = True
            item.deleted_at = deleted_at
            item.deleted_reason = "Lokaler Verlauf geleert"
            counters[key] += 1
            db.add(ActivityLog(
                action="soft_delete",
                content_type=content_type,
                content_id=item.id,
                old_value={"id": item.id},
                new_value={"is_deleted": True, "deleted_at": deleted_at.isoformat()},
                metadata_json={"source": "clear_history"},
            ))
    db.commit()
    return {"ok": True, "mode": "soft-delete", **counters}


@router.delete("/tasks/{local_task_id}", response_model=dict)
def delete_task(local_task_id: int, db: Session = Depends(get_db)):
    task = db.query(SunoTask).filter(SunoTask.id == local_task_id, SunoTask.is_deleted.is_(False)).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")
    task.is_deleted = True
    task.deleted_at = utc_now_naive()
    task.deleted_reason = "Lokaler Task gelöscht"
    db.add(ActivityLog(action="soft_delete", content_type="task", content_id=task.id, old_value={"id": task.id, "task_id": task.task_id}, new_value={"is_deleted": True, "deleted_at": task.deleted_at.isoformat()}))
    db.commit()
    return {"ok": True, "deleted_task_id": local_task_id, "mode": "soft-delete"}


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(db: Session = Depends(get_db)):
    return MusicService(db).list_tasks()


@router.get("/songs", response_model=list[SongRead])
def list_songs(limit: int = Query(250, ge=1, le=1000), db: Session = Depends(get_db)):
    # Read-only: liefert lokale Songs sortiert nach originalem Suno/SunoAPI-Datum,
    # wenn dieses in metadata_json vorhanden ist. Synchronisierung läuft separat
    # über POST /api/music/songs/sync-library.
    return MusicService(db).list_songs(limit=limit)


@router.post("/songs/sync-library", response_model=dict)
async def sync_song_rows_into_library(payload: dict | None = None, db: Session = Depends(get_db)):
    data = payload or {}
    dry_run = bool(data.get("dry_run", True))
    limit = int(data.get("limit") or 1000)
    task_ids = data.get("task_ids") or data.get("task_id")
    source_songs = data.get("source_songs")
    source_json = data.get("source_json")
    task_type = str(data.get("task_type") or "generate_music")
    result = await SongLibrarySyncService(db).sync_from_songs_and_cache(
        limit=limit,
        dry_run=dry_run,
        task_ids=task_ids,
        source_songs=source_songs,
        source_json=source_json,
        task_type=task_type,
    )
    severity = "info" if dry_run else "success"
    if result.warnings:
        severity = "warning"
    create_system_status_notification(
        db,
        event_type="song_library_sync_dry_run" if dry_run else "song_library_sync_completed",
        title="Songs → Library synchronisiert" if not dry_run else "Songs → Library geprüft",
        message=(
            f"Geprüft: {result.checked_songs} Songs, "
            f"Audio-Kandidaten: {result.candidates_found}, "
            f"erstellt: {result.created}, aktualisiert: {result.updated}, "
            f"externe Quellen geprüft: {result.source_rows_checked}, "
            f"extern importiert: {result.external_task_imported}, "
            f"lokal gecached: {result.cached_audio_files}, Cover gecached: {getattr(result, 'covers_cached', 0)}, "
            f"aus gelöschten Alttreffern neu aufgebaut: {getattr(result, 'recreated_deleted_matches', 0)}, "
            f"Cache-Fehler: {result.cache_failed}."
        ),
        severity=severity,
        target_tab="system",
        target_payload={
            "section": "song_library_sync",
            "dry_run": dry_run,
            "result": result.as_dict(),
        },
        commit=False,
    )
    db.commit()
    return result.as_dict()
