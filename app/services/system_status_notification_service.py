from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import StatusNotification
from app.utils.time_utils import utc_now_naive


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    # JSON-Spalten dürfen nur primitive/serialisierbare Werte bekommen.
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, (str, int, float, bool, list, dict)):
            cleaned[str(key)] = value
        else:
            cleaned[str(key)] = str(value)
    return cleaned


def create_system_status_notification(
    db: Session | None,
    *,
    event_type: str,
    title: str,
    message: str | None = None,
    severity: str = "info",
    status: str = "unread",
    target_tab: str = "status",
    target_payload: dict[str, Any] | None = None,
    content_type: str = "system",
    content_id: int | None = None,
    completed: bool = True,
    commit: bool = True,
) -> StatusNotification | None:
    """Create a user-visible system/status notification.

    The helper deliberately reuses the existing StatusNotification table.
    It does not create SunoTask rows and it does not add a new provider/job path.
    For post-restore actions where the caller's Session may be invalid, pass db=None;
    the helper opens a fresh SessionLocal and commits independently.
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        notification = StatusNotification(
            event_type=str(event_type or "system_event")[:120],
            title=str(title or "Systemmeldung")[:255],
            message=message,
            severity=str(severity or "info")[:40],
            status=str(status or "unread")[:40],
            content_type=content_type,
            content_id=content_id,
            target_tab=target_tab,
            target_payload=_safe_payload(target_payload),
            completed_at=utc_now_naive() if completed else None,
        )
        session.add(notification)
        if commit:
            session.commit()
            session.refresh(notification)
        return notification
    except Exception:
        if commit:
            try:
                session.rollback()
            except Exception:
                pass
        return None
    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                pass
