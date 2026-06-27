from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import SunoTask
from app.services.music_service import MusicService
from app.services.task_lifecycle_service import LOCAL_APP_TASK_TYPES, recover_stale_tasks

logger = logging.getLogger("songstudio.startup_recovery")

RECOVERABLE_STATUSES = [
    "SUBMITTED",
    "PENDING",
    "PROCESSING",
    "RUNNING",
    "QUEUED",
    "CREATED",
    "FIRST_SUCCESS",
    "TEXT_SUCCESS",
]


def _count_recoverable_tasks(db: Session) -> int:
    # Startup-Recovery darf nur externe SunoAPI-Tasks aktiv refreshen.
    # Lokale App-Jobs werden vom Watchdog finalisiert, weil sie keine externe
    # Suno Task-ID besitzen und sonst dauerhaft RUNNING bleiben können.
    return int(
        db.query(SunoTask)
        .filter(
            SunoTask.is_deleted.is_(False),
            SunoTask.task_id.isnot(None),
            ~SunoTask.task_type.in_(LOCAL_APP_TASK_TYPES),
            func.upper(SunoTask.status).in_(RECOVERABLE_STATUSES),
        )
        .count()
    )


def _status_summary(tasks: list[SunoTask]) -> dict[str, int]:
    counter = Counter(str(task.status or "UNKNOWN").upper() for task in tasks)
    return dict(sorted(counter.items()))


async def run_startup_task_recovery() -> None:
    """Refresh offene Suno-Tasks nach einem FastAPI-Neustart.

    Damit gehen Songs nicht verloren, wenn FastAPI während einer Generierung
    beendet wurde oder ein Suno-Webhook während der Downtime nicht ankam.
    Voraussetzung: Die externe Suno task_id wurde vorher lokal gespeichert.
    """

    settings = get_settings()

    if not settings.suno_startup_recovery_enabled:
        logger.info("Startup-Recovery offener Suno-Tasks ist deaktiviert.")
        return

    initial_delay = max(0, int(settings.suno_startup_recovery_initial_delay_seconds))
    interval = max(5, int(settings.suno_startup_recovery_interval_seconds))
    attempts = max(1, int(settings.suno_startup_recovery_attempts))
    limit = max(1, int(settings.suno_startup_recovery_limit))

    if initial_delay:
        await asyncio.sleep(initial_delay)

    if settings.task_watchdog_enabled:
        db = SessionLocal()
        try:
            watchdog = recover_stale_tasks(
                db,
                stale_after_minutes=max(1, int(settings.local_app_task_no_heartbeat_stale_minutes)),
                local_only=True,
                dry_run=False,
            )
            if watchdog.get("recovered_count"):
                logger.warning("Startup-Watchdog: hängende lokale Tasks beendet: %s", watchdog)
        except Exception:
            logger.exception("Startup-Watchdog: Fehler beim Bereinigen lokaler Tasks.")
        finally:
            db.close()

    for attempt in range(1, attempts + 1):
        db = SessionLocal()
        try:
            open_before = _count_recoverable_tasks(db)

            if open_before <= 0:
                logger.info(
                    "Startup-Recovery: keine offenen Suno-Tasks gefunden. attempt=%s/%s",
                    attempt,
                    attempts,
                )
                return

            logger.warning(
                "Startup-Recovery: prüfe offene Suno-Tasks. attempt=%s/%s open_before=%s limit=%s",
                attempt,
                attempts,
                open_before,
                limit,
            )

            refreshed = await MusicService(db).refresh_pending_tasks(limit=limit)
            open_after = _count_recoverable_tasks(db)

            logger.warning(
                "Startup-Recovery: Refresh abgeschlossen. attempt=%s/%s refreshed=%s status_summary=%s open_after=%s",
                attempt,
                attempts,
                len(refreshed),
                _status_summary(refreshed),
                open_after,
            )

            if open_after <= 0:
                logger.info("Startup-Recovery: alle offenen Suno-Tasks wurden abgeschlossen oder verarbeitet.")
                return

        except Exception:
            logger.exception(
                "Startup-Recovery: Fehler beim Prüfen offener Suno-Tasks. attempt=%s/%s",
                attempt,
                attempts,
            )
        finally:
            db.close()

        if attempt < attempts:
            await asyncio.sleep(interval)

    logger.warning(
        "Startup-Recovery: beendet, obwohl noch offene Suno-Tasks vorhanden sein können. attempts=%s",
        attempts,
    )


async def run_startup_library_repair() -> None:
    """Führt die Audio-Library-Reparatur EINMAL kurz nach dem Start aus.

    Läuft entkoppelt und im Thread (Datei-I/O + commit), damit der Event-Loop
    nicht blockiert. Ersetzt die frühere Reparatur im Read-Pfad
    (active_usable_audio_assets), die bei jedem Library-Poll einen
    SQLite-Schreiblock erzeugt hat.
    """

    settings = get_settings()
    if not getattr(settings, "startup_library_repair_enabled", True):
        return

    await asyncio.sleep(8)

    def _repair() -> dict:
        from app.services.audio_asset_repair_service import repair_audio_library

        db = SessionLocal()
        try:
            return repair_audio_library(db)
        finally:
            db.close()

    try:
        result = await asyncio.to_thread(_repair)
        logger.info("Startup-Library-Reparatur abgeschlossen: %s", {k: v for k, v in result.items() if k != "ok"})
    except Exception:
        logger.exception("Startup-Library-Reparatur fehlgeschlagen.")
