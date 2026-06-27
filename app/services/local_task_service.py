from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SunoTask
from app.utils.time_utils import utc_now_naive


ACTIVE_CANCEL_STATUSES = {"CANCEL_REQUESTED", "CANCELLING", "CANCELLED"}


def mark_task_started(task: SunoTask, *, progress: int = 0) -> None:
    now = utc_now_naive()
    task.started_at = task.started_at or now
    task.heartbeat_at = now
    task.progress = max(0, min(100, int(progress or 0)))
    task.completed_at = None


def mark_task_finished(task: SunoTask, *, status: str, progress: int | None = None) -> None:
    now = utc_now_naive()
    task.status = status
    task.heartbeat_at = now
    task.completed_at = now
    task.progress = max(0, min(100, int(100 if progress is None else progress)))


def touch_task(
    task_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    phase: str | None = None,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False)).first()
        if not task:
            return
        now = utc_now_naive()
        task.heartbeat_at = now
        task.started_at = task.started_at or now
        if status:
            task.status = status
        if progress is not None:
            task.progress = max(0, min(100, int(progress)))
        response_payload = task.response_payload if isinstance(task.response_payload, dict) else {}
        progress_payload = response_payload.get("progress") if isinstance(response_payload.get("progress"), dict) else {}
        progress_payload.update({
            "phase": phase or progress_payload.get("phase") or task.status,
            "message": message or progress_payload.get("message"),
            "percent": task.progress,
            "updated_at": now.isoformat(),
            "last_heartbeat_at": now.isoformat(),
        })
        if extra:
            progress_payload.update(extra)
        task.response_payload = {
            **response_payload,
            "local_task": True,
            "status": task.status,
            "progress": progress_payload,
            "heartbeat_at": now.isoformat(),
        }
        db.add(task)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def is_cancel_requested(task_or_id: SunoTask | int | None, db: Session | None = None) -> bool:
    if task_or_id is None:
        return False
    own_db = None
    task = task_or_id if isinstance(task_or_id, SunoTask) else None
    if task is None and task_or_id:
        own_db = db or SessionLocal()
        task = own_db.query(SunoTask).filter(SunoTask.id == int(task_or_id), SunoTask.is_deleted.is_(False)).first()
    try:
        if task is None:
            return True
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        response_payload = task.response_payload if isinstance(task.response_payload, dict) else {}
        result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        return bool(
            str(task.status or "").upper() in ACTIVE_CANCEL_STATUSES
            or request_payload.get("cancel_requested")
            or response_payload.get("cancel_requested")
            or result_payload.get("cancel_requested")
        )
    finally:
        if own_db is not None and own_db is not db:
            own_db.close()
