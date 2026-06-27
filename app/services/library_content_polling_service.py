from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AppSetting
from app.services.library_content_cache_service import cache_missing_library_content_once

logger = logging.getLogger("songstudio.library_content_polling")
AI_SETTINGS_KEY = "ai_chat_settings"


def _settings_value(db: Session) -> dict[str, Any]:
    row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
    if not row or not isinstance(row.value, dict):
        return {}
    return row.value


def load_library_content_polling_settings(db: Session) -> dict[str, Any]:
    value = _settings_value(db)
    enabled = bool(value.get("library_content_polling_enabled", False))
    try:
        interval_minutes = int(value.get("library_content_polling_interval_minutes", 15))
    except (TypeError, ValueError):
        interval_minutes = 15
    try:
        limit = int(value.get("library_content_polling_limit", 500))
    except (TypeError, ValueError):
        limit = 500
    return {
        "enabled": enabled,
        "interval_minutes": min(1440, max(1, interval_minutes)),
        "limit": min(5000, max(10, limit)),
    }


async def run_library_content_polling() -> None:
    """Prüft optional im Hintergrund auf fehlende Library-Inhalte.

    Die Schleife läuft dauerhaft, wird aber nur aktiv, wenn die Admin-Option
    `library_content_polling_enabled` gesetzt ist. Bei neu geladenen Inhalten
    wird eine normale Frontend-Statusbenachrichtigung erstellt.
    """
    await asyncio.sleep(30)
    while True:
        sleep_seconds = 60
        db = SessionLocal()
        try:
            settings = load_library_content_polling_settings(db)
            if settings["enabled"]:
                await cache_missing_library_content_once(
                    db,
                    limit=settings["limit"],
                    notify_always=False,
                    background=True,
                )
                sleep_seconds = settings["interval_minutes"] * 60
            else:
                sleep_seconds = 60
        except asyncio.CancelledError:
            db.close()
            raise
        except Exception as exc:
            logger.exception("Library-Content-Polling fehlgeschlagen: %s", exc)
            sleep_seconds = 60
        finally:
            db.close()
        await asyncio.sleep(sleep_seconds)
