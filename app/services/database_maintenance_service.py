from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine
from app.models import AudioAsset, AudioProject, AudioTranscript, Song, StatusNotification, SunoTask
from app.services.audio_asset_materialization_service import AudioAssetMaterializationService
from app.services.audio_asset_repair_service import is_audio_url
from app.services.audio_cache_service import collect_audio_candidates
from app.services.portable_backup_service import normalize_portable_paths, sqlite_database_path
from app.services.song_library_sync_service import SongLibrarySyncService
from app.services.task_lifecycle_service import recover_stale_tasks
from app.utils.time_utils import utc_now_naive


@dataclass(slots=True)
class MaintenanceAction:
    area: str
    code: str
    count: int = 0
    severity: str = "info"
    description: str = ""
    examples: list[dict[str, Any]] = field(default_factory=list)

    def add(self, example: dict[str, Any] | None = None, *, amount: int = 1) -> None:
        self.count += amount
        if example is not None and len(self.examples) < 5:
            self.examples.append(example)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MaintenanceResult:
    ok: bool
    dry_run: bool
    checked_at: str
    max_severity: str
    database: dict[str, Any]
    counts: dict[str, int]
    integrity: str
    backup_path: str | None = None
    actions: list[MaintenanceAction] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "checked_at": self.checked_at,
            "max_severity": self.max_severity,
            "database": self.database,
            "counts": self.counts,
            "integrity": self.integrity,
            "backup_path": self.backup_path,
            "summary": self.summary,
            "actions": [item.as_dict() for item in self.actions],
        }


_SEVERITY_ORDER = {"ok": 0, "info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}


def _utc_stamp() -> str:
    return utc_now_naive().strftime("%Y%m%d_%H%M%S")


def _safe_count(db: Session, model: Any) -> int:
    try:
        return int(db.query(model).count())
    except Exception:
        return 0


def _integrity_check() -> str:
    if not str(get_settings().database_url or "").startswith("sqlite"):
        return "not_sqlite"
    try:
        with engine.connect() as connection:
            return str(connection.execute(text("PRAGMA integrity_check")).scalar() or "unknown")
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc.__class__.__name__}"


def _sqlite_backup() -> Path | None:
    settings = get_settings()
    if not str(settings.database_url or "").startswith("sqlite"):
        return None
    source = sqlite_database_path()
    if not source.exists():
        return None
    target = settings.backup_storage_path / f"suno_fastapi_app.before-db-maintenance-{_utc_stamp()}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
        src.execute("PRAGMA wal_checkpoint(FULL)")
        src.backup(dst)
    return target


def _database_payload() -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {"url_safe": settings.database_url if "@" not in settings.database_url else "configured"}
    if str(settings.database_url or "").startswith("sqlite"):
        try:
            path = sqlite_database_path()
            payload.update({"path": str(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else 0})
        except Exception as exc:  # noqa: BLE001
            payload["error"] = f"{exc.__class__.__name__}: {exc}"
    return payload


def _collect_counts(db: Session) -> dict[str, int]:
    return {
        "suno_tasks": _safe_count(db, SunoTask),
        "songs": _safe_count(db, Song),
        "audio_assets": _safe_count(db, AudioAsset),
        "audio_projects": _safe_count(db, AudioProject),
        "audio_transcripts": _safe_count(db, AudioTranscript),
        "status_notifications": _safe_count(db, StatusNotification),
    }


def _max_severity(actions: list[MaintenanceAction], integrity: str) -> str:
    severity = "ok"
    if integrity != "ok" and integrity != "not_sqlite":
        severity = "critical"
    for action in actions:
        if action.count <= 0:
            continue
        if _SEVERITY_ORDER.get(action.severity, 0) > _SEVERITY_ORDER.get(severity, 0):
            severity = action.severity
    return severity


def _summarize(actions: list[MaintenanceAction]) -> dict[str, int]:
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "ok": 0}
    for action in actions:
        if action.count <= 0:
            continue
        key = action.severity if action.severity in summary else "info"
        summary[key] += int(action.count)
    return summary


def _active_asset_exists(db: Session, asset_id: int | None) -> bool:
    if not asset_id:
        return False
    return bool(db.query(AudioAsset.id).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first())


def _status_completed(value: str | None) -> bool:
    return str(value or "").strip().upper() in {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS", "CANCELLED", "FAILED"}


def inspect_database_maintenance(db: Session) -> dict[str, Any]:
    return run_database_maintenance(db, dry_run=True, backup=False, vacuum=False).as_dict()


def run_database_maintenance(
    db: Session,
    *,
    dry_run: bool = True,
    backup: bool = True,
    vacuum: bool = False,
    materialize_limit: int = 500,
) -> MaintenanceResult:
    settings = get_settings()
    actions: list[MaintenanceAction] = []
    integrity = _integrity_check()
    backup_path = None
    if backup and not dry_run and str(settings.database_url or "").startswith("sqlite"):
        backup_target = _sqlite_backup()
        backup_path = str(backup_target) if backup_target else None

    portable_action = MaintenanceAction(
        area="Pfade",
        code="PORTABLE_PATHS_NORMALIZED",
        severity="medium",
        description="Absolute oder nicht portable lokale Pfade wurden auf portable Storage-Pfade normalisiert.",
    )
    try:
        portable_result = normalize_portable_paths(db, dry_run=dry_run)
        changed = 0
        examples: list[dict[str, Any]] = []
        for key, stats in (portable_result.get("stats") or {}).items():
            changed += int(stats.get("changed") or 0)
            if stats.get("changed"):
                examples.append({"area": key, **stats})
        portable_action.count = changed
        portable_action.examples = examples[:5]
    except Exception as exc:  # noqa: BLE001
        portable_action.severity = "high"
        portable_action.add({"error": f"{exc.__class__.__name__}: {exc}"})
    actions.append(portable_action)

    materialize_action = MaintenanceAction(
        area="AudioAssets",
        code="TASK_AUDIO_ASSETS_MATERIALIZED",
        severity="medium",
        description="Erfolgreiche Task-Ergebnisse wurden in audio_assets nachgezogen.",
    )
    try:
        service = AudioAssetMaterializationService(db)
        aggregate = service.materialize_recent_tasks(limit=materialize_limit, force=True)
        materialize_action.count = int(aggregate.created + aggregate.updated + aggregate.skipped_deleted + getattr(aggregate, "recreated_deleted_matches", 0))
        if aggregate.created or aggregate.updated or aggregate.skipped_deleted or getattr(aggregate, "recreated_deleted_matches", 0):
            materialize_action.examples.append(aggregate.as_payload())
        if dry_run:
            db.rollback()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        materialize_action.severity = "high"
        materialize_action.add({"error": f"{exc.__class__.__name__}: {exc}"})
    actions.append(materialize_action)


    song_sync_action = MaintenanceAction(
        area="Songs",
        code="SONGS_SYNCED_TO_LIBRARY",
        severity="medium",
        description="Lokale /api/music/songs-Daten wurden als Quelle genutzt, um fehlende AudioAssets zu ergänzen und Original-Suno-Daten für neueste-zuerst-Sortierung zu normalisieren.",
    )
    try:
        sync_result = SongLibrarySyncService(db).sync_from_songs(limit=materialize_limit, dry_run=dry_run)
        song_sync_action.count = int(sync_result.created + sync_result.updated + sync_result.source_date_updates + sync_result.project_updates + sync_result.skipped_deleted + getattr(sync_result, "recreated_deleted_matches", 0))
        if song_sync_action.count:
            song_sync_action.examples = sync_result.examples[:5]
        if sync_result.warnings:
            song_sync_action.severity = "high"
            for warning in sync_result.warnings[:5]:
                song_sync_action.add({"warning": warning}, amount=0)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        song_sync_action.severity = "high"
        song_sync_action.add({"error": f"{exc.__class__.__name__}: {exc}"})
    actions.append(song_sync_action)

    missing_asset_action = MaintenanceAction(
        area="AudioAssets",
        code="SUCCESS_TASK_AUDIO_WITHOUT_ASSET",
        severity="high",
        description="Erfolgreiche Tasks liefern direkte Audio-URLs, haben aber keinen aktiven AudioAsset-Treffer.",
    )
    try:
        rows = (
            db.query(SunoTask)
            .filter(SunoTask.is_deleted.is_(False))
            .order_by(SunoTask.id.desc())
            .limit(max(1, int(materialize_limit)))
            .all()
        )
        for task in rows:
            if str(task.status or "").strip().upper() not in {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}:
                continue
            candidates = collect_audio_candidates({"response_payload": task.response_payload, "result_payload": task.result_payload})
            for candidate in candidates:
                if not candidate.source_url or not is_audio_url(candidate.source_url):
                    continue
                query = db.query(AudioAsset.id).filter(AudioAsset.is_deleted.is_(False))
                if candidate.audio_id:
                    exists = query.filter(AudioAsset.audio_id == str(candidate.audio_id)).first()
                else:
                    exists = query.filter(AudioAsset.source_url == candidate.source_url).first()
                if not exists:
                    missing_asset_action.add({"task_local_id": task.id, "task_id": task.task_id, "audio_id": candidate.audio_id, "source_url": candidate.source_url})
    except Exception as exc:  # noqa: BLE001
        missing_asset_action.add({"error": f"{exc.__class__.__name__}: {exc}"})
    actions.append(missing_asset_action)

    final_action = MaintenanceAction(
        area="Production",
        code="PROJECT_FINAL_ASSET_REPAIRED",
        severity="high",
        description="AudioProjects mit fehlendem/gelöschtem final_audio_asset_id wurden auf aktives Projekt-Asset gesetzt oder geleert.",
    )
    for project in db.query(AudioProject).filter(AudioProject.is_deleted.is_(False), AudioProject.final_audio_asset_id.isnot(None)).all():
        if _active_asset_exists(db, project.final_audio_asset_id):
            continue
        replacement = (
            db.query(AudioAsset)
            .filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False))
            .order_by(AudioAsset.is_final.desc(), AudioAsset.created_at.desc(), AudioAsset.id.desc())
            .first()
        )
        old_id = project.final_audio_asset_id
        new_id = replacement.id if replacement else None
        final_action.add({"project_id": project.id, "title": project.title, "old_final_audio_asset_id": old_id, "new_final_audio_asset_id": new_id})
        if not dry_run:
            project.final_audio_asset_id = new_id
            db.add(project)
    actions.append(final_action)

    transcript_action = MaintenanceAction(
        area="SRT",
        code="ORPHAN_TRANSCRIPTS_ARCHIVED",
        severity="high",
        description="Transcripts mit fehlendem/gelöschtem AudioAsset wurden als archived_orphan markiert.",
    )
    for transcript in db.query(AudioTranscript).all():
        if not transcript.audio_asset_id or _active_asset_exists(db, transcript.audio_asset_id):
            continue
        if str(transcript.status or "") == "archived_orphan":
            continue
        transcript_action.add({"transcript_id": transcript.id, "audio_asset_id": transcript.audio_asset_id, "old_status": transcript.status, "new_status": "archived_orphan"})
        if not dry_run:
            transcript.status = "archived_orphan"
            message = "Quell-AudioAsset fehlt oder ist gelöscht; durch DB-Wartung archiviert."
            transcript.error_message = f"{transcript.error_message}\n{message}".strip() if transcript.error_message else message
            db.add(transcript)
    actions.append(transcript_action)

    favorite_song_action = MaintenanceAction(
        area="Favoriten",
        code="SONG_FAVORITES_SYNCED",
        severity="medium",
        description="songs.is_favorite wurde aus aktiven AudioAsset-Favoriten synchronisiert.",
    )
    song_rows = db.execute(text("""
        SELECT s.id, s.title, COALESCE(s.is_favorite, 0) AS song_is_favorite,
               CASE WHEN SUM(CASE WHEN a.is_favorite = 1 THEN 1 ELSE 0 END) > 0 THEN 1 ELSE 0 END AS any_asset_favorite,
               GROUP_CONCAT(CASE WHEN a.is_favorite = 1 THEN a.id ELSE NULL END) AS favorite_asset_ids
        FROM songs s
        JOIN audio_assets a ON a.song_id = s.id AND COALESCE(a.is_deleted, 0) = 0
        WHERE COALESCE(s.is_deleted, 0) = 0
        GROUP BY s.id
        HAVING COALESCE(s.is_favorite, 0) != any_asset_favorite
    """)).mappings().all()
    for row in song_rows:
        favorite_song_action.add(dict(row))
        if not dry_run:
            song = db.query(Song).filter(Song.id == int(row["id"])).first()
            if song:
                song.is_favorite = bool(row["any_asset_favorite"])
                db.add(song)
    actions.append(favorite_song_action)

    favorite_project_action = MaintenanceAction(
        area="Favoriten",
        code="PROJECT_FAVORITES_SYNCED",
        severity="medium",
        description="audio_projects.is_favorite wurde aus aktiven AudioAsset-Favoriten synchronisiert.",
    )
    project_rows = db.execute(text("""
        SELECT p.id, p.title, COALESCE(p.is_favorite, 0) AS project_is_favorite,
               CASE WHEN SUM(CASE WHEN a.is_favorite = 1 THEN 1 ELSE 0 END) > 0 THEN 1 ELSE 0 END AS any_asset_favorite,
               GROUP_CONCAT(CASE WHEN a.is_favorite = 1 THEN a.id ELSE NULL END) AS favorite_asset_ids
        FROM audio_projects p
        JOIN audio_assets a ON a.project_id = p.id AND COALESCE(a.is_deleted, 0) = 0
        WHERE COALESCE(p.is_deleted, 0) = 0
        GROUP BY p.id
        HAVING COALESCE(p.is_favorite, 0) != any_asset_favorite
    """)).mappings().all()
    for row in project_rows:
        favorite_project_action.add(dict(row))
        if not dry_run:
            project = db.query(AudioProject).filter(AudioProject.id == int(row["id"])).first()
            if project:
                project.is_favorite = bool(row["any_asset_favorite"])
                db.add(project)
    actions.append(favorite_project_action)

    notifications_action = MaintenanceAction(
        area="Notifications",
        code="BATCH_NOTIFICATIONS_ROUTED_TO_STATUS",
        severity="medium",
        description="Batch-Erfolgsnotifications ohne einzelnes AudioAsset-Ziel wurden auf Statusdetails umgeleitet.",
    )
    batch_notifications = (
        db.query(StatusNotification)
        .filter(
            StatusNotification.is_deleted.is_(False),
            StatusNotification.event_type.like("bulk_%"),
            StatusNotification.target_tab == "library",
        )
        .all()
    )
    for notification in batch_notifications:
        payload = notification.target_payload if isinstance(notification.target_payload, dict) else {}
        if payload.get("audio_asset_id") or payload.get("primary_audio_asset_id") or payload.get("audio_asset_ids"):
            continue
        new_payload = dict(payload)
        new_payload.setdefault("notification_scope", "batch_summary")
        new_payload.setdefault("click_target", "status_detail")
        notifications_action.add({"notification_id": notification.id, "event_type": notification.event_type, "old_target_tab": notification.target_tab, "new_target_tab": "status"})
        if not dry_run:
            notification.target_tab = "status"
            notification.target_payload = new_payload
            db.add(notification)
    actions.append(notifications_action)

    stale_task_action = MaintenanceAction(
        area="Tasks",
        code="STALE_LOCAL_TASKS_RECOVERED",
        severity="medium",
        description="Hängende lokale Tasks wurden per Watchdog-Regel als stale erkannt und bei echtem Lauf bereinigt.",
    )
    try:
        stale_result = recover_stale_tasks(
            db,
            stale_after_minutes=settings.task_watchdog_stale_minutes,
            local_only=True,
            dry_run=dry_run,
        )
        affected = int(stale_result.get("recovered") or stale_result.get("would_recover") or len(stale_result.get("tasks") or []))
        stale_task_action.count = affected
        stale_task_action.examples = (stale_result.get("tasks") or [])[:5]
    except Exception as exc:  # noqa: BLE001
        stale_task_action.severity = "high"
        stale_task_action.add({"error": f"{exc.__class__.__name__}: {exc}"})
    actions.append(stale_task_action)

    vacuum_action = MaintenanceAction(
        area="SQLite",
        code="SQLITE_VACUUM_ANALYZE",
        severity="info",
        description="SQLite ANALYZE/VACUUM wurde ausgeführt oder vorgemerkt.",
    )
    if vacuum and str(settings.database_url or "").startswith("sqlite"):
        vacuum_action.count = 1
        if not dry_run:
            # VACUUM darf nicht innerhalb einer aktiven Transaktion laufen.
            try:
                db.commit()
            except Exception:
                db.rollback()
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.execute(text("PRAGMA wal_checkpoint(FULL)"))
                connection.execute(text("ANALYZE"))
                connection.execute(text("VACUUM"))
        else:
            vacuum_action.examples.append({"planned": True})
    actions.append(vacuum_action)

    if dry_run:
        db.rollback()
    else:
        db.commit()

    result = MaintenanceResult(
        ok=True,
        dry_run=dry_run,
        checked_at=utc_now_naive().isoformat(),
        max_severity="ok",
        database=_database_payload(),
        counts=_collect_counts(db),
        integrity=integrity,
        backup_path=backup_path,
        actions=actions,
    )
    result.max_severity = _max_severity(actions, integrity)
    result.ok = result.max_severity not in {"critical", "high"} and integrity in {"ok", "not_sqlite"}
    result.summary = _summarize(actions)
    return result
