from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import StatusNotification
from app.routers.notifications import (
    bulk_delete_notifications,
    bulk_mark_notifications_done,
    cleanup_stale_notifications,
    delete_notification,
    list_notifications,
    mark_notification_done,
)
from app.utils.time_utils import utc_now_naive


def _notification(title, *, status="unread", event_type="task_status", created_at=None):
    return StatusNotification(
        event_type=event_type,
        title=title,
        message="msg",
        severity="info",
        status=status,
        target_tab="status",
        target_payload={"task_local_id": 1},
        created_at=created_at or utc_now_naive(),
    )


def test_list_notifications_hides_done_and_deleted_by_flags(isolated_db_session):
    db = isolated_db_session
    unread = _notification("unread")
    done = _notification("done", status="done")
    deleted = _notification("deleted")
    deleted.is_deleted = True
    db.add_all([unread, done, deleted])
    db.commit()

    assert [row["title"] for row in list_notifications(include_done=False, include_deleted=False, db=db)] == ["unread"]
    titles = [row["title"] for row in list_notifications(include_done=True, include_deleted=True, db=db)]
    assert set(titles) == {"unread", "done", "deleted"}


def test_mark_done_bulk_done_delete_and_bulk_delete(isolated_db_session):
    db = isolated_db_session
    a = _notification("a")
    b = _notification("b")
    c = _notification("c")
    db.add_all([a, b, c])
    db.commit()

    assert mark_notification_done(a.id, db=db)["status"] == "done"
    bulk = bulk_mark_notifications_done({"ids": [str(b.id), "bad", 999999]}, db=db)
    assert bulk["updated"] == [b.id]

    assert delete_notification(c.id, db=db) == {"ok": True, "deleted": c.id}
    db.refresh(c)
    assert c.is_deleted is True

    empty = bulk_delete_notifications({"ids": []}, db=db)
    assert empty == {"ok": True, "deleted": []}

    with pytest.raises(HTTPException) as exc:
        mark_notification_done(999999, db=db)
    assert exc.value.status_code == 404


def test_cleanup_stale_notifications_finishes_old_running_statuses(isolated_db_session):
    db = isolated_db_session
    old_running = _notification(
        "old",
        status="unread",
        event_type="srt_generation_started",
        created_at=utc_now_naive() - timedelta(hours=8),
    )
    fresh_running = _notification(
        "fresh",
        status="unread",
        event_type="srt_generation_started",
        created_at=utc_now_naive(),
    )
    db.add_all([old_running, fresh_running])
    db.commit()

    result = cleanup_stale_notifications({"max_age_hours": 2}, db=db)
    db.refresh(old_running)
    db.refresh(fresh_running)

    assert result["ok"] is True
    assert old_running.status == "done"
    assert old_running.completed_at is not None
    assert fresh_running.status == "unread"
