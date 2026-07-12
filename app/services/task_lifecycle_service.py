from __future__ import annotations

# CORE CONTRACT
# Zweck: Zentrale Status-/Heartbeat-/Debug-Log-Schicht fuer lokale App-Tasks.
# Debug-Konvention: response_payload.debug_log enthaelt technische Ereignisse,
# response_payload.steps_log enthaelt nutzernahe Ablaufphasen. Werte werden
# vor Speicherung gekuerzt und sensible Keys redigiert.
# Neue lokale Task-Funktionen sollen diese Helper nutzen statt eigene inkompatible
# Debug-Strukturen in response_payload/result_payload zu schreiben.

import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import StatusNotification, SunoTask
from app.utils.time_utils import utc_now_naive

TASK_DEBUG_LOG_LIMIT = 200
TASK_STEP_LOG_LIMIT = 200
TASK_DEBUG_REDACT_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "bearer",
}

ACTIVE_TASK_STATUSES = {
    "SUBMITTED",
    "PENDING",
    "PROCESSING",
    "RUNNING",
    "QUEUED",
    "CREATED",
    "FIRST_SUCCESS",
    "TEXT_SUCCESS",
    "CANCEL_REQUESTED",
}

TERMINAL_TASK_STATUSES = {
    "SUCCESS",
    "COMPLETED",
    "COMPLETE",
    "DONE",
    "FAILED",
    "ERROR",
    "CANCELLED",
    "PARTIAL_SUCCESS",
    "COMPLETED_MANUAL",
}

LOCAL_APP_TASK_TYPES = {
    "generate_srt",
    "generate_stems",
    "bulk_generate_srt",
    "bulk_generate_stems",
    "generate_cover_art",
    "audio_ai_analysis",
    "library_ai_tagging",
    "bulk_library_ai_tagging",
    "convert_to_wav_local",
    "manual_audio_import",
    "library_repair",
    "library_content_cache",
    "import_suno_song",
    "import_suno_song_batch",
    "import_sunoapi_task_batch",
    "opencli_generate_music",
    "generate_music_opencli",
    "daw_arrangement_render",
    "maintenance_audit",
    "maintenance_repair",
}


def utcnow() -> datetime:
    return utc_now_naive()


def is_terminal_status(status: str | None) -> bool:
    return str(status or "").strip().upper() in TERMINAL_TASK_STATUSES


def is_active_status(status: str | None) -> bool:
    return str(status or "").strip().upper() in ACTIVE_TASK_STATUSES


def is_local_app_task(task: SunoTask | None) -> bool:
    if not task:
        return False
    task_type = str(task.task_type or "").strip()
    request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
    response_payload = task.response_payload if isinstance(task.response_payload, dict) else {}
    return (
        task_type in LOCAL_APP_TASK_TYPES
        or bool(request_payload.get("local_task"))
        or bool(request_payload.get("background"))
        or bool(response_payload.get("background"))
        or (not task.task_id and is_active_status(task.status))
    )


def _merge_payload(original: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(original) if isinstance(original, dict) else {}
    if isinstance(patch, dict):
        base.update(patch)
    return base


def _safe_debug_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "<max-depth>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in TASK_DEBUG_REDACT_KEYS or any(part in key_text.lower() for part in ("token", "secret", "password", "authorization")):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = _safe_debug_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        limit = 80
        result = [_safe_debug_value(item, depth=depth + 1) for item in value[:limit]]
        if len(value) > limit:
            result.append(f"<truncated {len(value) - limit} items>")
        return result
    if isinstance(value, tuple):
        return [_safe_debug_value(item, depth=depth + 1) for item in value[:80]]
    if isinstance(value, str):
        return value if len(value) <= 4000 else f"{value[:4000]}... <truncated {len(value) - 4000} chars>"
    return value


def _append_payload_list(payload: dict[str, Any] | None, key: str, item: dict[str, Any], limit: int) -> dict[str, Any]:
    base = dict(payload) if isinstance(payload, dict) else {}
    rows = list(base.get(key) or []) if isinstance(base.get(key), list) else []
    rows.append(item)
    if len(rows) > limit:
        rows = rows[-limit:]
    base[key] = rows
    return base


def append_task_debug_event(
    db: Session,
    task_or_id: SunoTask | int | None,
    *,
    event: str,
    detail: str | None = None,
    level: str = "info",
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> SunoTask | None:
    if task_or_id is None:
        return None
    task = task_or_id if isinstance(task_or_id, SunoTask) else db.query(SunoTask).filter(SunoTask.id == int(task_or_id)).first()
    if not task:
        return None
    now = utcnow()
    item = {
        "at": now.isoformat(),
        "level": str(level or "info").lower(),
        "event": str(event or "debug_event"),
        "detail": str(detail or ""),
    }
    if data:
        item["data"] = _safe_debug_value(data)
    task.response_payload = _append_payload_list(task.response_payload, "debug_log", item, TASK_DEBUG_LOG_LIMIT)
    task.response_payload["last_debug_event"] = item
    db.add(task)
    if commit:
        db.commit()
        db.refresh(task)
    return task


def append_task_step_log(
    db: Session,
    task_or_id: SunoTask | int | None,
    *,
    phase: str,
    phase_label: str | None = None,
    detail: str | None = None,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> SunoTask | None:
    if task_or_id is None:
        return None
    task = task_or_id if isinstance(task_or_id, SunoTask) else db.query(SunoTask).filter(SunoTask.id == int(task_or_id)).first()
    if not task:
        return None
    item = {
        "at": utcnow().isoformat(),
        "phase": str(phase or "step"),
        "phase_label": str(phase_label or phase or "Schritt"),
        "detail": str(detail or ""),
    }
    if data:
        item["data"] = _safe_debug_value(data)
    task.response_payload = _append_payload_list(task.response_payload, "steps_log", item, TASK_STEP_LOG_LIMIT)
    db.add(task)
    if commit:
        db.commit()
        db.refresh(task)
    return task


def mark_task_started(db: Session, task: SunoTask, *, payload: dict[str, Any] | None = None) -> SunoTask:
    now = utcnow()
    task.status = "RUNNING"
    task.started_at = task.started_at or now
    task.heartbeat_at = now
    task.completed_at = None
    task.cancel_requested = False
    task.response_payload = _merge_payload(task.response_payload, {"background": True, "status": "RUNNING", **(payload or {})})
    append_task_debug_event(
        db,
        task,
        event="task_started",
        detail="Task wurde gestartet.",
        data={"task_type": task.task_type, "status": task.status, "payload": payload or {}},
        commit=False,
    )
    append_task_step_log(
        db,
        task,
        phase="started",
        phase_label="Task gestartet",
        detail="Task wurde in den RUNNING-Status gesetzt.",
        data={"task_type": task.task_type},
        commit=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def heartbeat_task(
    db: Session,
    task_or_id: SunoTask | int | None,
    *,
    progress: dict[str, Any] | None = None,
    status: str = "RUNNING",
    commit: bool = True,
) -> SunoTask | None:
    if task_or_id is None:
        return None
    task = task_or_id if isinstance(task_or_id, SunoTask) else db.query(SunoTask).filter(SunoTask.id == int(task_or_id)).first()
    if not task:
        return None
    now = utcnow()
    if not task.started_at:
        task.started_at = now
    task.heartbeat_at = now
    if status:
        task.status = status
    task.response_payload = _merge_payload(task.response_payload, {"background": True, "status": task.status, "progress": progress or {}, "heartbeat_at": now.isoformat()})
    db.add(task)
    if commit:
        db.commit()
        db.refresh(task)
    return task


def is_cancel_requested(db: Session, task_or_id: SunoTask | int | None) -> bool:
    if task_or_id is None:
        return False
    task = task_or_id if isinstance(task_or_id, SunoTask) else db.query(SunoTask).filter(SunoTask.id == int(task_or_id)).first()
    if not task:
        return False
    return bool(task.cancel_requested) or str(task.status or "").upper() == "CANCEL_REQUESTED"


def request_task_cancel(db: Session, task_id: int, *, reason: str | None = None) -> SunoTask | None:
    task = db.query(SunoTask).filter(SunoTask.id == int(task_id), SunoTask.is_deleted.is_(False)).first()
    if not task:
        return None
    now = utcnow()
    task.cancel_requested = True
    if is_active_status(task.status):
        task.status = "CANCEL_REQUESTED"
    task.response_payload = _merge_payload(task.response_payload, {"cancel_requested": True, "cancel_requested_at": now.isoformat(), "cancel_reason": reason})
    db.add(task)
    db.add(StatusNotification(
        event_type="task_cancel_requested",
        title=f"Abbruch angefordert: {task.task_type}",
        message=reason or "Der lokale Job wird beim nächsten sicheren Prüfpunkt abgebrochen.",
        severity="warning",
        status="unread",
        task_local_id=task.id,
        suno_task_id=task.task_id,
        content_type="task_status",
        content_id=task.id,
        target_tab="status",
        target_payload={"task_local_id": task.id, "task_type": task.task_type, "status": "CANCEL_REQUESTED"},
    ))
    db.commit()
    db.refresh(task)
    return task


def finish_open_task_notifications(db: Session, task: SunoTask, *, message: str | None = None) -> int:
    now = utcnow()
    rows = (
        db.query(StatusNotification)
        .filter(
            StatusNotification.task_local_id == task.id,
            StatusNotification.status != "done",
            StatusNotification.is_deleted.is_(False),
        )
        .all()
    )
    count = 0
    for row in rows:
        # Finale Error/Success-Benachrichtigungen bleiben sichtbar; nur laufende Info-Meldungen werden abgeschlossen.
        if str(row.severity or "").lower() in {"error", "warning"} and row.completed_at:
            continue
        if str(row.event_type or "").endswith(("_completed", "_failed", "_cancelled")):
            continue
        row.status = "done"
        row.completed_at = row.completed_at or now
        if message:
            row.message = message
        db.add(row)
        count += 1
    return count


def mark_task_finished(
    db: Session,
    task_or_id: SunoTask | int | None,
    *,
    status: str,
    message: str | None = None,
    result_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
    notify: bool = False,
) -> SunoTask | None:
    if task_or_id is None:
        return None
    task = task_or_id if isinstance(task_or_id, SunoTask) else db.query(SunoTask).filter(SunoTask.id == int(task_or_id)).first()
    if not task:
        return None
    now = utcnow()
    task.status = status
    task.completed_at = now
    task.heartbeat_at = now
    task.error_message = None if status in {"SUCCESS", "PARTIAL_SUCCESS", "COMPLETED", "COMPLETE", "DONE", "CANCELLED"} else (message or task.error_message)
    if result_payload is not None:
        task.result_payload = result_payload
    task.response_payload = _merge_payload(task.response_payload, {"status": status, "completed_at": now.isoformat(), **(response_payload or {})})
    append_task_debug_event(
        db,
        task,
        event="task_finished",
        detail=message or f"Task abgeschlossen: {status}",
        level="info" if status in {"SUCCESS", "PARTIAL_SUCCESS", "COMPLETED", "COMPLETE", "DONE", "CANCELLED"} else "error",
        data={"task_type": task.task_type, "status": status, "result_payload": result_payload or {}},
        commit=False,
    )
    append_task_step_log(
        db,
        task,
        phase="completed" if status in {"SUCCESS", "COMPLETED", "COMPLETE", "DONE"} else str(status).lower(),
        phase_label="Task abgeschlossen",
        detail=message or status,
        data={"task_type": task.task_type, "status": status},
        commit=False,
    )
    finish_open_task_notifications(db, task, message=f"Abgeschlossen: {message or status}")
    db.add(task)
    if notify:
        severity = "success" if status in {"SUCCESS", "COMPLETED", "DONE"} else ("warning" if status in {"PARTIAL_SUCCESS", "CANCELLED"} else "error")
        db.add(StatusNotification(
            event_type=f"{task.task_type}_{str(status).lower()}",
            title=f"Task {status}: {task.task_type}",
            message=message or status,
            severity=severity,
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task_status",
            content_id=task.id,
            target_tab="status",
            target_payload={"task_local_id": task.id, "task_type": task.task_type, "status": status},
            completed_at=now,
        ))
    db.commit()
    db.refresh(task)
    return task


# Heartbeat-bewusste Stale-Limits pro lokalem Task-Typ. Lange Jobs (Stems/Bulk)
# dürfen mit frischem Heartbeat NICHT als hängend gewertet werden, sonst killt ein
# periodischer Watchdog legitime Läufe. Worker OHNE jeden Heartbeat (z.B. nie
# gestartet / Prozessstart fehlgeschlagen) werden hingegen schnell finalisiert.
LOCAL_APP_TASK_STALE_LIMITS_MINUTES: dict[str, int] = {
    "generate_srt": 30,
    "bulk_generate_srt": 25,
    "generate_stems": 45,
    "bulk_generate_stems": 45,
    "generate_cover_art": 20,
    "audio_ai_analysis": 30,
    "convert_to_wav_local": 20,
    "manual_audio_import": 20,
    "import_suno_song": 30,
    "import_suno_song_batch": 30,
    "import_sunoapi_task_batch": 30,
    "opencli_generate_music": 30,
    "maintenance_audit": 60,
    "maintenance_repair": 60,
}
DEFAULT_LOCAL_TASK_STALE_MINUTES = 30
NO_HEARTBEAT_STALE_MINUTES = 5


def _task_has_heartbeat(task: SunoTask) -> bool:
    if getattr(task, "heartbeat_at", None):
        return True
    payload = task.response_payload if isinstance(task.response_payload, dict) else {}
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    return bool(progress.get("updated_at") or progress.get("last_heartbeat_at") or payload.get("heartbeat_at"))


def _task_last_activity(task: SunoTask) -> datetime | None:
    if getattr(task, "heartbeat_at", None):
        return task.heartbeat_at
    payload = task.response_payload if isinstance(task.response_payload, dict) else {}
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    for source in (progress, payload):
        for key in ("updated_at", "last_heartbeat_at", "started_at", "heartbeat_at"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    continue
    return task.heartbeat_at or task.updated_at or task.started_at or task.created_at


def _effective_stale_minutes(task: SunoTask, override_minutes: int | None) -> int:
    # Expliziter Override (Startup-Recovery / manueller Admin-Call) gewinnt für alle
    # Typen – beim Startup sind laufende lokale Tasks ohnehin verwaist.
    if override_minutes and int(override_minutes) > 0:
        return int(override_minutes)
    type_limit = LOCAL_APP_TASK_STALE_LIMITS_MINUTES.get(task.task_type, DEFAULT_LOCAL_TASK_STALE_MINUTES)
    if _task_has_heartbeat(task):
        return type_limit
    # Ohne jeden Heartbeat: aggressiv finalisieren, aber nie strenger als das Typlimit.
    return min(type_limit, NO_HEARTBEAT_STALE_MINUTES)


def recover_stale_tasks(
    db: Session,
    *,
    stale_after_minutes: int | None = None,
    local_only: bool = True,
    dry_run: bool = True,
    task_ids: list[int] | None = None,
) -> dict[str, Any]:
    now = utcnow()
    query = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False), func.upper(SunoTask.status).in_(ACTIVE_TASK_STATUSES))
    if task_ids:
        query = query.filter(SunoTask.id.in_([int(item) for item in task_ids if int(item) > 0]))
    rows = query.order_by(SunoTask.updated_at.asc()).all()
    stale: list[dict[str, Any]] = []
    skipped_external = 0
    touched_notifications = 0
    for task in rows:
        local = is_local_app_task(task)
        if local_only and not local:
            skipped_external += 1
            continue
        last_seen = _task_last_activity(task)
        limit_minutes = _effective_stale_minutes(task, stale_after_minutes)
        cutoff = now - timedelta(minutes=max(1, int(limit_minutes)))
        if last_seen and last_seen > cutoff:
            continue
        idle_minutes = round(max(0.0, (now - last_seen).total_seconds() / 60.0), 1) if last_seen else None
        stale.append({
            "id": task.id,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status,
            "local_task": local,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "idle_minutes": idle_minutes,
            "stale_limit_minutes": limit_minutes,
            "had_heartbeat": _task_has_heartbeat(task),
        })
        if dry_run:
            continue
        task.status = "FAILED"
        task.error_message = (
            f"Watchdog: Task seit ~{idle_minutes} Minuten ohne Heartbeat/Update "
            f"(Limit {limit_minutes} Minuten). Automatisch beendet."
        )
        task.completed_at = now
        task.heartbeat_at = now
        task.response_payload = _merge_payload(task.response_payload, {"status": "FAILED", "watchdog_recovered": True, "completed_at": now.isoformat()})
        touched_notifications += finish_open_task_notifications(db, task, message="Abgeschlossen: Watchdog hat den hängenden Task beendet.")
        db.add(task)
        db.add(StatusNotification(
            event_type="task_watchdog_recovered",
            title=f"Hängender Task beendet: {task.task_type}",
            message=task.error_message,
            severity="warning",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task_status",
            content_id=task.id,
            target_tab="status",
            target_payload={"task_local_id": task.id, "task_type": task.task_type, "status": "FAILED", "watchdog_recovered": True},
            completed_at=now,
        ))
    if not dry_run:
        db.commit()
    return {
        "ok": True,
        "dry_run": dry_run,
        "stale_after_minutes": stale_after_minutes,
        "heartbeat_aware": not bool(stale_after_minutes and int(stale_after_minutes) > 0),
        "candidates": len(rows),
        "stale_count": len(stale),
        "recovered_count": 0 if dry_run else len(stale),
        "skipped_external": skipped_external,
        "notifications_closed": touched_notifications,
        "stale_tasks": stale,
    }


async def run_periodic_task_watchdog() -> None:
    """Periodischer Watchdog-Loop für hängende lokale Background-Tasks.

    Läuft als entkoppelter asyncio-Task. Nutzt die heartbeat-bewusste Per-Typ-
    Logik (kein globaler Override), damit lange Stem-/Bulk-Jobs mit frischem
    Heartbeat NICHT fälschlich finalisiert werden, abgestürzte/verwaiste Jobs
    ohne Heartbeat aber zuverlässig in FAILED überführt werden. Jeder Durchlauf
    nutzt eine kurze, eigene DB-Session.
    """

    import asyncio
    import logging

    from app.config import get_settings
    from app.database import SessionLocal

    logger = logging.getLogger("songstudio.task_watchdog")
    settings = get_settings()

    if not getattr(settings, "task_watchdog_enabled", True):
        logger.info("Periodischer Task-Watchdog ist deaktiviert.")
        return

    interval = max(30, int(getattr(settings, "task_watchdog_interval_seconds", 120)))
    await asyncio.sleep(min(interval, 45))

    while True:
        db = SessionLocal()
        try:
            result = recover_stale_tasks(db, stale_after_minutes=None, local_only=True, dry_run=False)
            if result.get("recovered_count"):
                logger.warning("Task-Watchdog hat hängende lokale Tasks beendet: %s", result.get("stale_tasks"))
        except asyncio.CancelledError:
            db.close()
            raise
        except Exception:
            logger.exception("Periodischer Task-Watchdog-Durchlauf fehlgeschlagen.")
        finally:
            db.close()
        await asyncio.sleep(interval)


@contextmanager
def task_heartbeat_ticker(task_id: int, *, interval_seconds: int = 30):
    """Context-Manager-Variante von :func:`start_task_heartbeat`."""

    stop = start_task_heartbeat(task_id, interval_seconds=interval_seconds)
    try:
        yield
    finally:
        stop()


def start_task_heartbeat(task_id: int, *, interval_seconds: int = 30):
    """Hält den Heartbeat eines lokalen Background-Tasks frisch, solange der Job läuft.

    Ein Daemon-Thread aktualisiert ``heartbeat_at`` periodisch (kurze, eigene
    DB-Session). Stockt der Worker (Deadlock, hängender In-Process-Call) oder
    stirbt er, versiegt der Heartbeat sofort und der Watchdog kann den Task am
    Per-Typ-Limit zuverlässig finalisieren – ohne legitime, lang laufende
    I/O-/Subprozess-Items (Groq-HTTP, demucs) fälschlich zu beenden, weil deren
    GIL/Loop den Ticker weiterlaufen lässt. Gibt eine Stop-Funktion zurück.
    """

    stop = threading.Event()

    def _run() -> None:
        from app.database import SessionLocal

        while not stop.wait(max(5, int(interval_seconds))):
            db = SessionLocal()
            try:
                task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
                if not task or is_terminal_status(task.status):
                    return
                now = utcnow()
                task.heartbeat_at = now
                payload = task.response_payload if isinstance(task.response_payload, dict) else {}
                payload["heartbeat_at"] = now.isoformat()
                progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
                progress["last_heartbeat_at"] = now.isoformat()
                payload["progress"] = progress
                task.response_payload = payload
                db.add(task)
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

    thread = threading.Thread(target=_run, name=f"hb-{task_id}", daemon=True)
    thread.start()
    return stop.set
