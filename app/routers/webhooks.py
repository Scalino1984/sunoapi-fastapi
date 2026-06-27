from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SunoTask
from app.schemas import WebhookPayload
from app.services.music_service import MusicService


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/suno")
async def suno_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    body = payload.model_dump(exclude_none=True)
    task_id = payload.task_id or payload.id or body.get("taskId")

    task = None
    if task_id:
        task = db.query(SunoTask).filter(SunoTask.task_id == str(task_id)).first()

    if task:
        task.result_payload = body
        task.status = payload.status or body.get("status") or body.get("msg") or task.status
        task.error_message = payload.error or body.get("error")
        db.commit()
        db.refresh(task)
        service = MusicService(db)
        song = service._upsert_song_from_task(task)
        await service._cache_audio_if_configured(task, song=song)

    return {"ok": True}
