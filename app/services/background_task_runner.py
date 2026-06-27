from __future__ import annotations

import asyncio
import inspect
import logging
import multiprocessing
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker-Registry + Reaper
# ---------------------------------------------------------------------------
# Lange Jobs (Demucs/WhisperX/Batch-Import) laufen in eigenen Prozessen, damit
# Audio-Streaming, Statuspolling und der React-Player nicht blockieren. Wenn ein
# solcher Worker hart stirbt (OOM, Segfault, kill, Fork-Deadlock), kann er seinen
# eigenen Task nicht mehr als FAILED finalisieren. Ohne Aufräumung bliebe der Task
# dauerhaft RUNNING und die Notification unread. Der Reaper sammelt beendete
# Prozesse ein (gegen Zombies bei daemon=False) und finalisiert bei nicht-null
# Exitcode den zugehörigen lokalen Task – aber nur, wenn er noch aktiv ist.

@dataclass
class _WorkerHandle:
    name: str
    handle: Any  # multiprocessing.Process | threading.Thread
    finalize_task_id: int | None = None
    is_process: bool = True
    started_at: float = field(default_factory=time.monotonic)


_WORKERS: dict[int, _WorkerHandle] = {}
_WORKERS_LOCK = threading.Lock()
_REAPER_THREAD: threading.Thread | None = None
_REAPER_LOCK = threading.Lock()
_REAPER_INTERVAL_SECONDS = 5.0


def _start_method() -> str:
    try:
        from app.config import get_settings

        configured = str(getattr(get_settings(), "background_worker_start_method", "thread") or "thread").strip().lower()
    except Exception:
        configured = "thread"
    if configured not in {"spawn", "fork", "thread", "auto"}:
        configured = "thread"
    if configured == "auto":
        # Fork nach gestartetem Event-Loop/torch ist auf WSL2 deadlock-anfällig,
        # daher ist spawn die sichere Standardwahl.
        return "spawn"
    return configured


def _dispose_inherited_sqlalchemy_connections() -> None:
    try:
        from app.database import engine

        engine.dispose(close=False)
    except Exception:
        logger.debug("SQLAlchemy engine dispose in worker failed", exc_info=True)


def _finalize_crashed_task(task_id: int, *, exitcode: int | None, name: str) -> None:
    """Finalisiert einen lokalen Task, dessen Worker-Prozess hart gestorben ist.

    Überschreibt bewusst NUR noch aktive Tasks. Hat der Worker selbst bereits
    SUCCESS/FAILED geschrieben (sauberer Pfad), passiert hier nichts.
    """

    try:
        from app.database import SessionLocal
        from app.models import SunoTask
        from app.services.task_lifecycle_service import is_active_status, mark_task_finished
    except Exception:
        logger.exception("Crash-Finalizer konnte Abhängigkeiten nicht laden (Task %s).", task_id)
        return

    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if not task or not is_active_status(task.status):
            return
        message = (
            f"Background-Worker '{name}' wurde unerwartet beendet "
            f"(Exitcode {exitcode}). Task automatisch als FAILED finalisiert."
        )
        mark_task_finished(
            db,
            task,
            status="FAILED",
            message=message,
            response_payload={"crashed": True, "exitcode": exitcode, "worker_name": name},
            notify=True,
        )
        logger.warning("Crash-Finalizer: Task %s nach Worker-Absturz beendet (%s).", task_id, name)
    except Exception:
        logger.exception("Crash-Finalizer ist für Task %s fehlgeschlagen.", task_id)
        db.rollback()
    finally:
        db.close()


def _reap_once() -> None:
    finished: list[_WorkerHandle] = []
    with _WORKERS_LOCK:
        for key, worker in list(_WORKERS.items()):
            handle = worker.handle
            alive = handle.is_alive()
            if not alive:
                finished.append(worker)
                _WORKERS.pop(key, None)

    for worker in finished:
        handle = worker.handle
        exitcode: int | None = None
        if worker.is_process:
            try:
                handle.join(timeout=1.0)  # reap zombie
            except Exception:
                pass
            exitcode = getattr(handle, "exitcode", None)
        # Threads können einen harten Crash nicht überleben lassen (gemeinsamer
        # Prozess), daher nur Prozesse mit Exitcode != 0 nach-finalisieren.
        if worker.is_process and worker.finalize_task_id and exitcode not in (0, None):
            _finalize_crashed_task(worker.finalize_task_id, exitcode=exitcode, name=worker.name)


def _reaper_loop() -> None:
    # Dauerhafter Daemon: vernachlässigbarer Overhead, dafür keine Race-/Lock-
    # Ordering-Risiken durch Selbst-Terminierung.
    while True:
        time.sleep(_REAPER_INTERVAL_SECONDS)
        try:
            _reap_once()
        except Exception:
            logger.exception("Background-Reaper-Durchlauf fehlgeschlagen.")


def _ensure_reaper_running() -> None:
    global _REAPER_THREAD
    with _REAPER_LOCK:
        if _REAPER_THREAD is not None and _REAPER_THREAD.is_alive():
            return
        thread = threading.Thread(target=_reaper_loop, name="bg-worker-reaper", daemon=True)
        _REAPER_THREAD = thread
        thread.start()


def _register(worker: _WorkerHandle) -> None:
    with _WORKERS_LOCK:
        _WORKERS[id(worker.handle)] = worker
    _ensure_reaper_running()


def _detached_process_entry(target: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """Process entrypoint for isolated long-running jobs."""

    _dispose_inherited_sqlalchemy_connections()
    try:
        result = target(*args, **kwargs)
        if inspect.isawaitable(result):
            asyncio.run(result)
    except Exception:
        logger.exception("Detached background process failed: %s", getattr(target, "__name__", "background-job"))
        # Nicht-null Exit signalisiert dem Reaper einen Fehlerlauf, falls der
        # Worker seinen Task nicht selbst finalisiert hat.
        raise SystemExit(1)


def _resolve_finalize_task_id(finalize_task_id: int | None, args: tuple[Any, ...]) -> int | None:
    if finalize_task_id is not None:
        try:
            value = int(finalize_task_id)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
        # Ungültiger expliziter Wert (z.B. 0) -> auf Konvention zurückfallen.
    # Konvention: alle Worker erhalten die lokale Task-ID als erstes Argument.
    if args:
        first = args[0]
        if isinstance(first, int) and first > 0:
            return first
    return None


def run_detached_process(
    name: str,
    target: Callable[..., Any],
    *args: Any,
    finalize_task_id: int | None = None,
    **kwargs: Any,
) -> multiprocessing.Process | threading.Thread:
    """Run a long job outside of the ASGI worker process.

    Standard ist 'spawn' (sicher nach gestartetem Event-Loop/torch). 'fork' bleibt
    optional per Setting, ist auf WSL2 aber deadlock-anfällig. Schlägt der
    Prozessstart fehl, wird auf den Daemon-Thread-Runner zurückgefallen.
    """

    safe_name = "-".join(str(name or "background-job").strip().split())[:80] or "background-job"
    method = _start_method()
    finalize_id = _resolve_finalize_task_id(finalize_task_id, args)

    if method == "thread":
        return run_detached_background(safe_name, target, *args, finalize_task_id=finalize_id, **kwargs)

    try:
        ctx = multiprocessing.get_context(method)
        process = ctx.Process(target=_detached_process_entry, name=safe_name, args=(target, args, kwargs), daemon=False)
        process.start()
        _register(_WorkerHandle(name=safe_name, handle=process, finalize_task_id=finalize_id, is_process=True))
        return process
    except Exception:
        logger.exception("Could not start detached process %s (%s); falling back to thread", safe_name, method)
        return run_detached_background(safe_name, target, *args, finalize_task_id=finalize_id, **kwargs)


def run_detached_background(
    name: str,
    target: Callable[..., Any],
    *args: Any,
    finalize_task_id: int | None = None,
    **kwargs: Any,
) -> threading.Thread:
    """Run a long job in its own daemon thread without blocking the ASGI event loop."""

    safe_name = "-".join(str(name or "background-job").strip().split())[:80] or "background-job"
    finalize_id = _resolve_finalize_task_id(finalize_task_id, args)

    def _runner() -> None:
        _dispose_inherited_sqlalchemy_connections()
        try:
            result = target(*args, **kwargs)
            if inspect.isawaitable(result):
                asyncio.run(result)
        except Exception:
            logger.exception("Detached background worker failed: %s", safe_name)
            if finalize_id:
                _finalize_crashed_task(finalize_id, exitcode=None, name=safe_name)

    thread = threading.Thread(target=_runner, name=safe_name, daemon=True)
    thread.start()
    _register(_WorkerHandle(name=safe_name, handle=thread, finalize_task_id=finalize_id, is_process=False))
    return thread
