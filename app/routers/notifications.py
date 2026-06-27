from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import StatusNotification
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _to_dict(row: StatusNotification) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "title": row.title,
        "message": row.message,
        "severity": row.severity,
        "status": row.status,
        "task_local_id": row.task_local_id,
        "suno_task_id": row.suno_task_id,
        "content_type": row.content_type,
        "content_id": row.content_id,
        "target_tab": row.target_tab,
        "target_payload": row.target_payload,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "is_deleted": row.is_deleted,
    }


@router.get("")
def list_notifications(include_done: bool = True, include_deleted: bool = False, limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(StatusNotification)
    if not include_deleted:
        query = query.filter(StatusNotification.is_deleted.is_(False))
    if not include_done:
        query = query.filter(StatusNotification.status != "done")
    rows = query.order_by(StatusNotification.created_at.desc()).limit(min(max(limit, 1), 1000)).all()
    return [_to_dict(row) for row in rows]


@router.post("/cleanup-stale")
def cleanup_stale_notifications(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)):
    payload = payload or {}
    try:
        max_age_hours = float(payload.get("max_age_hours", 24))
    except (TypeError, ValueError):
        max_age_hours = 24
    max_age_hours = min(max(max_age_hours, 1), 24 * 30)

    allowed_severities = payload.get("severities") or ["info", "success"]
    allowed_severities = [str(item).lower() for item in allowed_severities if str(item).strip()]
    if not allowed_severities:
        allowed_severities = ["info", "success"]

    cutoff = utc_now_naive() - timedelta(hours=max_age_hours)
    dry_run = bool(payload.get("dry_run", False))

    query = (
        db.query(StatusNotification)
        .filter(StatusNotification.is_deleted.is_(False))
        .filter(StatusNotification.status != "done")
        .filter(StatusNotification.created_at < cutoff)
        .filter(StatusNotification.severity.in_(allowed_severities))
    )
    rows = query.order_by(StatusNotification.created_at.asc()).limit(1000).all()

    if not dry_run:
        now = utc_now_naive()
        for row in rows:
            row.status = "done"
            row.completed_at = row.completed_at or now
        db.commit()

    return {
        "ok": True,
        "dry_run": dry_run,
        "max_age_hours": max_age_hours,
        "updated": [] if dry_run else [row.id for row in rows],
        "matched": [row.id for row in rows],
    }


@router.post("/{notification_id}/done")
def mark_notification_done(notification_id: int, db: Session = Depends(get_db)):
    row = db.query(StatusNotification).filter(StatusNotification.id == notification_id, StatusNotification.is_deleted.is_(False)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Benachrichtigung wurde nicht gefunden.")
    row.status = "done"
    db.commit()
    db.refresh(row)
    return _to_dict(row)


@router.post("/bulk-done")
def bulk_mark_notifications_done(payload: dict[str, Any], db: Session = Depends(get_db)):
    ids = [int(item) for item in payload.get("ids", []) if str(item).isdigit()]
    if not ids:
        return {"ok": True, "updated": []}
    rows = db.query(StatusNotification).filter(StatusNotification.id.in_(ids), StatusNotification.is_deleted.is_(False)).all()
    for row in rows:
        row.status = "done"
    db.commit()
    return {"ok": True, "updated": [row.id for row in rows]}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db)):
    row = db.query(StatusNotification).filter(StatusNotification.id == notification_id, StatusNotification.is_deleted.is_(False)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Benachrichtigung wurde nicht gefunden.")
    row.is_deleted = True
    row.deleted_at = utc_now_naive()
    row.deleted_reason = "Vom Benutzer aus der Statusübersicht gelöscht."
    db.commit()
    return {"ok": True, "deleted": notification_id}


@router.post("/bulk-delete")
def bulk_delete_notifications(payload: dict[str, Any], db: Session = Depends(get_db)):
    ids = [int(item) for item in payload.get("ids", []) if str(item).isdigit()]
    if not ids:
        return {"ok": True, "deleted": []}
    rows = db.query(StatusNotification).filter(StatusNotification.id.in_(ids), StatusNotification.is_deleted.is_(False)).all()
    now = utc_now_naive()
    for row in rows:
        row.is_deleted = True
        row.deleted_at = now
        row.deleted_reason = "Mehrfachauswahl in der Statusübersicht gelöscht."
    db.commit()
    return {"ok": True, "deleted": [row.id for row in rows]}
