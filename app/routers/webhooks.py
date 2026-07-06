from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SunoTask
from app.schemas import WebhookPayload
from app.services.music_service import MusicService
from app.services.video_asset_service import VideoAssetService, extract_video_status, is_video_success_status


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _nested_data(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def _webhook_task_id(payload: WebhookPayload, body: dict[str, Any]) -> str | None:
    nested = _nested_data(body)
    value = (
        payload.task_id
        or payload.id
        or body.get("taskId")
        or body.get("task_id")
        or nested.get("task_id")
        or nested.get("taskId")
        or nested.get("id")
    )
    return str(value) if value else None


def _webhook_status(payload: WebhookPayload, body: dict[str, Any]) -> str:
    nested = _nested_data(body)
    code = body.get("code")
    callback_type = str(nested.get("callbackType") or nested.get("callback_type") or body.get("callbackType") or "").strip().lower()
    explicit_status = payload.status or body.get("status") or nested.get("status") or nested.get("state")

    if explicit_status:
        return str(explicit_status)
    if code is not None and str(code) != "200":
        return "FAILED"
    if callback_type == "complete":
        return "SUCCESS"
    if callback_type == "first":
        return "FIRST_SUCCESS"
    if callback_type == "text":
        return "TEXT_SUCCESS"
    if callback_type == "error":
        return "FAILED"
    # Fallback fuer aeltere/abweichende Providerantworten: msg ist kein stabiler
    # Taskstatus, deshalb nur eindeutig positive Meldungen auf SUCCESS mappen.
    msg = str(body.get("msg") or "").strip().lower()
    if code == 200 and any(token in msg for token in ("success", "generated", "complete")):
        return "SUCCESS"
    return str(body.get("msg") or "RUNNING")


@router.post("/suno")
async def suno_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    body = payload.model_dump(exclude_none=True)
    task_id = _webhook_task_id(payload, body)

    task = None
    if task_id:
        task = db.query(SunoTask).filter(SunoTask.task_id == str(task_id)).first()

    if task:
        task.result_payload = body
        task.status = extract_video_status(body) if task.task_type == "create_video" else _webhook_status(payload, body)
        task.status = task.status or _webhook_status(payload, body)
        task.error_message = payload.error or body.get("error") or (body.get("msg") if str(body.get("code") or "200") != "200" else None)
        db.commit()
        db.refresh(task)
        service = MusicService(db)
        song = service._upsert_song_from_task(task)
        if task.task_type == "create_video":
            if is_video_success_status(task.status):
                VideoAssetService(db).materialize_video_task(task, song=song, cache=True)
        else:
            await service._cache_audio_if_configured(task, song=song)

    return {"ok": True}
