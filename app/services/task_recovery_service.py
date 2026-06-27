"""Kompatibilitäts-Shim.

Die früher hier doppelt gepflegte Stale-Recovery-Logik wurde in
``task_lifecycle_service`` konsolidiert (heartbeat-bewusst + Per-Typ-Limits),
um Drift zwischen zwei „Wahrheiten" über hängende Tasks zu vermeiden. Dieses
Modul bleibt nur als dünner Delegationslayer für eventuelle Altimporte erhalten.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.task_lifecycle_service import (  # noqa: F401
    LOCAL_APP_TASK_STALE_LIMITS_MINUTES,
    is_local_app_task,
    recover_stale_tasks,
)


def recover_stale_local_tasks(
    db: Session,
    *,
    dry_run: bool = False,
    stale_after_minutes: int | None = None,
    task_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Deprecated: delegiert an die konsolidierte heartbeat-bewusste Recovery."""

    return recover_stale_tasks(
        db,
        stale_after_minutes=stale_after_minutes,
        local_only=True,
        dry_run=dry_run,
        task_ids=task_ids,
    )
