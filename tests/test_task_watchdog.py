"""Tests für die konsolidierte, heartbeat-bewusste Stale-Task-Recovery und die
Finalize-ID-Auflösung des Background-Runners.

Diese Tests decken die Kernregel des Bugfixes ab: lange Jobs mit frischem
Heartbeat dürfen NICHT finalisiert werden, verwaiste/abgestürzte Jobs ohne
Heartbeat hingegen schnell.
"""

import os
import tempfile
from datetime import datetime, timedelta
from app.utils.time_utils import utc_now_naive

# In-Memory/Tempfile-DB, bevor app.database den Engine baut.
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import SunoTask  # noqa: E402
from app.services.task_lifecycle_service import (  # noqa: E402
    _effective_stale_minutes,
    recover_stale_tasks,
)
from app.services.background_task_runner import _resolve_finalize_task_id  # noqa: E402


def setup_module(module):
    Base.metadata.create_all(bind=engine)


def teardown_module(module):
    try:
        os.unlink(_TMP_DB.name)
    except OSError:
        pass


def _make_task(db, *, task_type, status="RUNNING", heartbeat_minutes_ago=None, created_minutes_ago=200):
    now = utc_now_naive()
    hb = None if heartbeat_minutes_ago is None else now - timedelta(minutes=heartbeat_minutes_ago)
    task = SunoTask(
        task_id=None,
        task_type=task_type,
        status=status,
        request_payload={"local_task": True},
        response_payload={"local_task": True, "status": status},
        started_at=now - timedelta(minutes=created_minutes_ago),
        heartbeat_at=hb,
        created_at=now - timedelta(minutes=created_minutes_ago),
        updated_at=hb or (now - timedelta(minutes=created_minutes_ago)),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_fresh_heartbeat_long_job_is_kept():
    db = SessionLocal()
    try:
        # Stems-Job, Heartbeat vor 30 min -> Limit 120 min -> NICHT stale.
        task = _make_task(db, task_type="generate_stems", heartbeat_minutes_ago=30)
        result = recover_stale_tasks(db, dry_run=False)
        db.refresh(task)
        assert task.status == "RUNNING"
        assert all(item["id"] != task.id for item in result["stale_tasks"])
    finally:
        db.close()


def test_stale_heartbeat_long_job_is_recovered():
    db = SessionLocal()
    try:
        # Stems-Job, Heartbeat vor 200 min -> über 120-min-Limit -> stale.
        task = _make_task(db, task_type="generate_stems", heartbeat_minutes_ago=200)
        result = recover_stale_tasks(db, dry_run=False)
        db.refresh(task)
        assert task.status == "FAILED"
        assert any(item["id"] == task.id for item in result["stale_tasks"])
        assert result["recovered_count"] >= 1
    finally:
        db.close()


def test_no_heartbeat_job_recovered_fast():
    db = SessionLocal()
    try:
        # Kein Heartbeat, gestartet vor 20 min -> No-Heartbeat-Limit 5 min -> stale.
        task = _make_task(db, task_type="bulk_generate_srt", heartbeat_minutes_ago=None, created_minutes_ago=20)
        recover_stale_tasks(db, dry_run=False)
        db.refresh(task)
        assert task.status == "FAILED"
    finally:
        db.close()


def test_dry_run_does_not_mutate():
    db = SessionLocal()
    try:
        task = _make_task(db, task_type="generate_stems", heartbeat_minutes_ago=300)
        result = recover_stale_tasks(db, dry_run=True)
        db.refresh(task)
        assert task.status == "RUNNING"
        assert result["recovered_count"] == 0
        assert result["stale_count"] >= 1
    finally:
        db.close()


def test_override_minutes_beats_type_limit():
    db = SessionLocal()
    try:
        # Override 10 min (z.B. Startup-Recovery): selbst frischer Heartbeat (15 min)
        # liegt darüber -> stale.
        task = _make_task(db, task_type="generate_stems", heartbeat_minutes_ago=15)
        recover_stale_tasks(db, stale_after_minutes=10, dry_run=False)
        db.refresh(task)
        assert task.status == "FAILED"
    finally:
        db.close()


def test_effective_stale_minutes_heartbeat_awareness():
    class _T:
        task_type = "generate_stems"
        heartbeat_at = utc_now_naive()
        response_payload = {}

    with_hb = _T()
    assert _effective_stale_minutes(with_hb, None) == 45

    no_hb = _T()
    no_hb.heartbeat_at = None
    assert _effective_stale_minutes(no_hb, None) == 5

    # Override gewinnt immer.
    assert _effective_stale_minutes(with_hb, 10) == 10


def test_resolve_finalize_task_id():
    assert _resolve_finalize_task_id(None, (42, {"ids": [1]})) == 42
    assert _resolve_finalize_task_id(7, ("x",)) == 7
    assert _resolve_finalize_task_id(None, ("not-an-int",)) is None
    assert _resolve_finalize_task_id(None, ()) is None
    assert _resolve_finalize_task_id(0, (5,)) == 5  # 0 ist kein gültiger Override -> Fallback args[0]
