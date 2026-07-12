from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal
from app.models import (
    ActivityLog,
    AiChatSession,
    AudioAsset,
    AudioProject,
    AudioTranscript,
    Playlist,
    PlaylistItem,
    Song,
    StatusNotification,
    SunoTask,
    User,
    VideoAsset,
)
from app.services.audit_registry_service import AUDIT_CHECKS, normalize_check_ids
from app.services.background_task_runner import run_detached_background
from app.services.import_provenance_service import (
    has_false_manual_sunoapi_import_marker,
    strip_manual_sunoapi_import_source,
)
from app.services.portable_path_service import project_root, resolve_portable_path, to_portable_path
from app.services.task_lifecycle_service import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    heartbeat_task,
    is_cancel_requested,
    mark_task_finished,
    mark_task_started,
    recover_stale_tasks,
)
from app.utils.time_utils import utc_now_naive

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
TERMINAL_SUCCESS = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS"}
REPORT_ROOT = project_root() / "storage" / "reports" / "audits"

REPAIR_ACTION_PLAN_KEYS: dict[str, tuple[str, str]] = {
    "remove_false_manual_sunoapi_import_marker": ("imports.provenance", "candidate_task_ids"),
    "recover_stale_task": ("workflow.tasks", "stale_task_ids"),
    "backfill_task_completed_at": ("workflow.tasks", "terminal_task_ids_without_completed_at"),
    "complete_terminal_task_notification": ("workflow.tasks", "open_terminal_notification_ids"),
    "archive_orphan_transcript": ("database.references", "orphan_transcript_ids"),
}


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _best_task_completion_timestamp(task: SunoTask) -> tuple[datetime, str]:
    candidates = [
        (task.heartbeat_at, "heartbeat_at"),
        (task.updated_at, "updated_at"),
        (task.started_at, "started_at"),
        (task.created_at, "created_at"),
    ]
    available = [(value, source) for value, source in candidates if value is not None]
    if not available:
        return utc_now_naive(), "current_time"
    value, source = max(available, key=lambda item: item[0])
    return value, source


def _is_progress_notification_event(event_type: Any) -> bool:
    value = str(event_type or "").strip().lower()
    if not value:
        return False
    if value in {"task_status", "task_progress", "task_started", "task_running", "task_queued", "task_processing"}:
        return True
    return value.endswith(("_started", "_progress", "_running", "_queued", "_processing", "_pending"))


def _finding(
    *,
    code: str,
    severity: str,
    title: str,
    message: str,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    details: dict[str, Any] | None = None,
    repairable: bool = False,
    repair_action: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details or {},
        "repairable": bool(repairable),
        "repair_action": repair_action,
    }


def _max_severity(findings: list[dict[str, Any]]) -> str:
    severity = "info"
    for item in findings:
        candidate = str(item.get("severity") or "info")
        if SEVERITY_ORDER.get(candidate, 0) > SEVERITY_ORDER.get(severity, 0):
            severity = candidate
    return severity


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    result = {key: 0 for key in ("critical", "high", "medium", "low", "info")}
    for item in findings:
        key = str(item.get("severity") or "info")
        result[key if key in result else "info"] += 1
    return result


def _problem_type_count(results: list[dict[str, Any]]) -> int:
    keys: set[tuple[str, str, str]] = set()
    for result in results or []:
        check_id = str(result.get("check_id") or "unknown")
        for finding in result.get("findings") or []:
            severity = str(finding.get("severity") or "info")
            code = str(finding.get("code") or finding.get("title") or "UNKNOWN_FINDING")
            keys.add((check_id, severity, code))
    return len(keys)


def _repair_result_summary(actions: dict[str, Any], selected_actions: list[str] | None = None) -> dict[str, int]:
    """Erzeugt eine stabile, kompakte Reparaturzusammenfassung für API und UI.

    Die vorhandenen Reparaturservices behalten ihre jeweiligen Detailformate.
    Diese Funktion verdichtet ausschließlich die bekannten Zähler, ohne die
    Reparaturlogik oder deren Ergebnisse umzudeuten.
    """

    changed = 0
    skipped = 0
    failed = 0

    provenance = _safe_dict(actions.get("imports.provenance"))
    if provenance:
        changed += sum(int(value or 0) for value in provenance.values() if isinstance(value, (int, float)))

    references = _safe_dict(actions.get("database.references"))
    orphan_result = _safe_dict(references.get("archive_orphan_transcript"))
    changed += int(orphan_result.get("archived") or 0)
    skipped += int(orphan_result.get("already_archived") or 0)

    workflow = _safe_dict(actions.get("workflow.tasks"))
    backfill_result = _safe_dict(workflow.get("backfill_task_completed_at"))
    changed += int(backfill_result.get("backfilled") or 0)
    skipped += int(backfill_result.get("already_completed") or 0)

    notification_result = _safe_dict(workflow.get("complete_terminal_task_notification"))
    changed += int(notification_result.get("completed") or 0)
    skipped += int(notification_result.get("already_completed") or 0)

    stale_result = _safe_dict(workflow.get("recover_stale_task"))
    changed += int(stale_result.get("recovered_count") or 0)
    skipped += int(stale_result.get("skipped_external") or 0)

    return {
        "action_count": len([item for item in (selected_actions or []) if str(item).strip()]),
        "changed_records": changed,
        "skipped_records": skipped,
        "failed_records": failed,
    }


def _check_result(check_id: str, findings: list[dict[str, Any]], *, summary: dict[str, Any] | None = None, repair_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = AUDIT_CHECKS[check_id]
    return {
        "check_id": check_id,
        "title": metadata["title"],
        "category": metadata["category"],
        "ok": not any(SEVERITY_ORDER.get(str(item.get("severity") or "info"), 0) >= SEVERITY_ORDER["high"] for item in findings),
        "max_severity": _max_severity(findings),
        "counts": _counts(findings),
        "finding_count": len(findings),
        "repairable_count": sum(1 for item in findings if item.get("repairable")),
        "summary": summary or {},
        "findings": findings,
        "repair_plan": repair_plan or {},
    }


def _limit_findings(findings: list[dict[str, Any]], parameters: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    limit = max(10, min(int(parameters.get("max_findings") or 1000), 5000))
    return findings[:limit], len(findings) > limit


def check_database_integrity(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:
    check_id = "database.integrity"
    findings: list[dict[str, Any]] = []
    bind = db.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name
    integrity = "not_applicable"
    if dialect == "sqlite":
        statement = "PRAGMA integrity_check" if bool(parameters.get("full_integrity_check")) else "PRAGMA quick_check"
        rows = db.execute(text(statement)).fetchall()
        integrity = "; ".join(str(row[0]) for row in rows) if rows else "unknown"
        if integrity.lower() != "ok":
            findings.append(_finding(code="DATABASE_INTEGRITY_FAILED", severity="critical", title="Datenbankintegrität fehlgeschlagen", message=integrity))
    else:
        db.execute(text("SELECT 1"))
        integrity = "reachable"

    actual_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    for table in sorted(model_tables - actual_tables):
        findings.append(_finding(code="SCHEMA_TABLE_MISSING", severity="critical", title="Tabelle fehlt", message=f"Die modellierte Tabelle {table} fehlt in der Datenbank.", entity_type="table", entity_id=table))
    for table in sorted(model_tables & actual_tables):
        actual_columns = {column["name"] for column in inspector.get_columns(table)}
        expected_columns = {column.name for column in Base.metadata.tables[table].columns}
        for column in sorted(expected_columns - actual_columns):
            findings.append(_finding(code="SCHEMA_COLUMN_MISSING", severity="critical", title="Spalte fehlt", message=f"{table}.{column} fehlt.", entity_type="column", entity_id=f"{table}.{column}"))

    try:
        from app.database import _PERFORMANCE_INDEXES  # bestehende zentrale Indexdefinition
        existing_by_table = {table: {item.get("name") for item in inspector.get_indexes(table)} for table in actual_tables}
        for index_name, table_cols in _PERFORMANCE_INDEXES:
            table = str(table_cols).split("(", 1)[0].strip()
            if table not in actual_tables:
                findings.append(_finding(code="INDEX_TARGET_TABLE_MISSING", severity="low", title="Indexziel fehlt", message=f"Index {index_name} verweist auf die nicht vorhandene Tabelle {table}.", entity_type="index", entity_id=index_name))
            elif index_name not in existing_by_table.get(table, set()):
                findings.append(_finding(code="PERFORMANCE_INDEX_MISSING", severity="medium", title="Performance-Index fehlt", message=f"Index {index_name} auf {table} fehlt.", entity_type="index", entity_id=index_name))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(code="INDEX_AUDIT_FAILED", severity="medium", title="Indexprüfung unvollständig", message=f"{exc.__class__.__name__}: {exc}"))

    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(check_id, limited, summary={"dialect": dialect, "integrity": integrity, "model_tables": len(model_tables), "database_tables": len(actual_tables), "truncated": truncated})


def _orphan_rows(db: Session, model: Any, foreign_column: Any, target_model: Any, target_column: Any, *, filters: list[Any] | None = None) -> list[Any]:
    query = db.query(model).outerjoin(target_model, foreign_column == target_column).filter(foreign_column.isnot(None), target_column.is_(None))
    for condition in filters or []:
        query = query.filter(condition)
    return query.all()


def check_database_references(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:
    check_id = "database.references"
    findings: list[dict[str, Any]] = []
    orphan_transcript_ids: list[int] = []
    active_asset = AudioAsset.is_deleted.is_(False)
    active_song = Song.is_deleted.is_(False)

    specs = [
        ("AUDIO_TASK_ORPHAN", "AudioAsset ohne Task", AudioAsset, AudioAsset.task_local_id, SunoTask, SunoTask.id, [active_asset]),
        ("AUDIO_SONG_ORPHAN", "AudioAsset ohne Song", AudioAsset, AudioAsset.song_id, Song, Song.id, [active_asset]),
        ("AUDIO_PROJECT_ORPHAN", "AudioAsset ohne Projekt", AudioAsset, AudioAsset.project_id, AudioProject, AudioProject.id, [active_asset]),
        ("VIDEO_AUDIO_ORPHAN", "Video ohne AudioAsset", VideoAsset, VideoAsset.audio_asset_id, AudioAsset, AudioAsset.id, [VideoAsset.is_deleted.is_(False)]),
        ("VIDEO_TASK_ORPHAN", "Video ohne Task", VideoAsset, VideoAsset.task_local_id, SunoTask, SunoTask.id, [VideoAsset.is_deleted.is_(False)]),
        ("PLAYLIST_ITEM_PLAYLIST_ORPHAN", "Playlist-Eintrag ohne Playlist", PlaylistItem, PlaylistItem.playlist_id, Playlist, Playlist.id, []),
        ("PLAYLIST_ITEM_AUDIO_ORPHAN", "Playlist-Eintrag ohne AudioAsset", PlaylistItem, PlaylistItem.audio_asset_id, AudioAsset, AudioAsset.id, []),
        ("PROJECT_FINAL_ASSET_ORPHAN", "Projekt mit ungültigem Final-Asset", AudioProject, AudioProject.final_audio_asset_id, AudioAsset, AudioAsset.id, [AudioProject.is_deleted.is_(False)]),
        ("CHAT_USER_ORPHAN", "KI-Chat ohne Benutzer", AiChatSession, AiChatSession.user_id, User, User.id, [AiChatSession.is_deleted.is_(False)]),
    ]
    for code, title, model, foreign_column, target_model, target_column, filters in specs:
        for row in _orphan_rows(db, model, foreign_column, target_model, target_column, filters=filters):
            findings.append(_finding(code=code, severity="high", title=title, message=f"{model.__tablename__} #{row.id} verweist auf einen fehlenden Datensatz.", entity_type=model.__tablename__, entity_id=row.id, details={"foreign_value": getattr(row, foreign_column.key)}))

    for transcript in _orphan_rows(db, AudioTranscript, AudioTranscript.audio_asset_id, AudioAsset, AudioAsset.id):
        status = str(transcript.status or "").strip().lower()
        # Bereits bewusst archivierte Alttranskripte bleiben nachvollziehbar,
        # gelten aber nicht mehr als offene Referenzverletzung.
        if status == "archived_orphan":
            continue
        orphan_transcript_ids.append(transcript.id)
        findings.append(_finding(
            code="TRANSCRIPT_AUDIO_ORPHAN",
            severity="high",
            title="Transcript ohne AudioAsset",
            message=f"audio_transcripts #{transcript.id} verweist auf einen fehlenden Datensatz.",
            entity_type="audio_transcripts",
            entity_id=transcript.id,
            details={
                "foreign_value": transcript.audio_asset_id,
                "status": transcript.status,
                "srt_path": transcript.srt_path,
            },
            repairable=True,
            repair_action="archive_orphan_transcript",
        ))

    for model in (SunoTask, Song, AudioAsset, VideoAsset, AudioProject, Playlist, AiChatSession):
        if not hasattr(model, "is_deleted"):
            continue
        rows = db.query(model).filter(
            ((model.is_deleted.is_(True)) & (model.deleted_at.is_(None))) |
            ((model.is_deleted.is_(False)) & (model.deleted_at.isnot(None)))
        ).all()
        for row in rows:
            findings.append(_finding(code="SOFT_DELETE_INCONSISTENT", severity="medium", title="Papierkorbzustand widersprüchlich", message=f"{model.__tablename__} #{row.id}: is_deleted und deleted_at passen nicht zusammen.", entity_type=model.__tablename__, entity_id=row.id, details={"is_deleted": bool(row.is_deleted), "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None}))

    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(
        check_id,
        limited,
        summary={"truncated": truncated},
        repair_plan={"orphan_transcript_ids": orphan_transcript_ids},
    )


def check_import_provenance(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:
    check_id = "imports.provenance"
    findings: list[dict[str, Any]] = []
    candidate_ids: list[int] = []
    tasks = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.asc()).all()
    for task in tasks:
        if not has_false_manual_sunoapi_import_marker(task_type=task.task_type, request_payload=task.request_payload, response_payload=task.response_payload):
            continue
        candidate_ids.append(task.id)
        linked_songs = db.query(Song.id).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).count() if task.task_id else 0
        linked_assets = db.query(AudioAsset.id).filter(AudioAsset.is_deleted.is_(False), ((AudioAsset.task_local_id == task.id) | (AudioAsset.suno_task_id == task.task_id))).count()
        findings.append(_finding(code="FALSE_MANUAL_SUNOAPI_IMPORT", severity="high", title="Falsche Import-Provenienz", message=f"Task #{task.id} besitzt lokale Generierungsmerkmale, ist aber als manueller SunoAPI.org-Import markiert.", entity_type="suno_tasks", entity_id=task.id, details={"task_id": task.task_id, "task_type": task.task_type, "status": task.status, "linked_songs": linked_songs, "linked_audio_assets": linked_assets}, repairable=True, repair_action="remove_false_manual_sunoapi_import_marker"))
    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(check_id, limited, summary={"candidate_task_count": len(candidate_ids), "truncated": truncated}, repair_plan={"candidate_task_ids": candidate_ids})


def _task_asset_key(task: SunoTask) -> str | None:
    payload = _safe_dict(task.request_payload)
    value = payload.get("audio_asset_id") or payload.get("asset_id") or payload.get("audioAssetId")
    return str(value) if value not in (None, "") else None


def check_workflow_tasks(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:
    check_id = "workflow.tasks"
    findings: list[dict[str, Any]] = []
    stale_result = recover_stale_tasks(db, stale_after_minutes=parameters.get("stale_after_minutes"), local_only=True, dry_run=True)
    stale_ids = [int(item["id"]) for item in stale_result.get("stale_tasks") or []]
    terminal_without_completed_at_ids: list[int] = []
    open_terminal_notification_ids: list[int] = []
    for item in stale_result.get("stale_tasks") or []:
        findings.append(_finding(code="STALE_LOCAL_TASK", severity="high", title="Hängender lokaler Task", message=f"Task #{item['id']} ist seit {item.get('idle_minutes')} Minuten ohne aktuellen Heartbeat.", entity_type="suno_tasks", entity_id=item["id"], details=item, repairable=True, repair_action="recover_stale_task"))

    tasks = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).all()
    active_groups: dict[tuple[str, str], list[SunoTask]] = {}
    for task in tasks:
        status = str(task.status or "").upper()
        if task.progress < 0 or task.progress > 100:
            findings.append(_finding(code="TASK_PROGRESS_INVALID", severity="medium", title="Ungültiger Task-Fortschritt", message=f"Task #{task.id} besitzt progress={task.progress}.", entity_type="suno_tasks", entity_id=task.id))
        if status in TERMINAL_TASK_STATUSES and not task.completed_at:
            suggested_at, timestamp_source = _best_task_completion_timestamp(task)
            terminal_without_completed_at_ids.append(task.id)
            findings.append(_finding(
                code="TERMINAL_TASK_WITHOUT_COMPLETED_AT",
                severity="medium",
                title="Abgeschlossener Task ohne Abschlusszeit",
                message=f"Task #{task.id} hat Status {status}, aber kein completed_at.",
                entity_type="suno_tasks",
                entity_id=task.id,
                details={
                    "status": status,
                    "task_type": task.task_type,
                    "suggested_completed_at": suggested_at.isoformat(),
                    "timestamp_source": timestamp_source,
                },
                repairable=True,
                repair_action="backfill_task_completed_at",
            ))
        if status in ACTIVE_TASK_STATUSES and task.completed_at:
            findings.append(_finding(code="ACTIVE_TASK_WITH_COMPLETED_AT", severity="high", title="Aktiver Task mit Abschlusszeit", message=f"Task #{task.id} ist aktiv, besitzt aber completed_at.", entity_type="suno_tasks", entity_id=task.id))
        if status in {"FAILED", "ERROR"} and not str(task.error_message or "").strip():
            findings.append(_finding(code="FAILED_TASK_WITHOUT_ERROR", severity="low", title="Fehlgeschlagener Task ohne Fehlertext", message=f"Task #{task.id} enthält keinen Fehlertext.", entity_type="suno_tasks", entity_id=task.id))
        if status in ACTIVE_TASK_STATUSES:
            asset_key = _task_asset_key(task)
            if asset_key:
                active_groups.setdefault((task.task_type, asset_key), []).append(task)

    for (task_type, asset_key), rows in active_groups.items():
        if len(rows) <= 1:
            continue
        findings.append(_finding(code="DUPLICATE_ACTIVE_TASK", severity="high", title="Doppelte aktive Verarbeitung", message=f"{len(rows)} aktive Tasks vom Typ {task_type} bearbeiten AudioAsset {asset_key}.", entity_type="suno_tasks", entity_id=",".join(str(row.id) for row in rows), details={"task_ids": [row.id for row in rows], "task_type": task_type, "audio_asset_id": asset_key}))

    terminal_ids = [task.id for task in tasks if str(task.status or "").upper() in TERMINAL_TASK_STATUSES]
    if terminal_ids:
        open_notifications = db.query(StatusNotification).filter(StatusNotification.is_deleted.is_(False), StatusNotification.task_local_id.in_(terminal_ids), StatusNotification.status != "done").all()
        for notification in open_notifications:
            event_type = str(notification.event_type or "").lower()
            # Finale Erfolgs-/Fehlerbenachrichtigungen bleiben absichtlich als
            # nutzerseitig ungelesene Meldungen sichtbar. Inkonsistent sind nur
            # alte Start-/Fortschrittsmeldungen ohne Abschlusskennzeichen.
            if notification.completed_at or event_type.endswith(("_completed", "_failed", "_cancelled")):
                continue
            if not _is_progress_notification_event(event_type):
                continue
            open_terminal_notification_ids.append(notification.id)
            findings.append(_finding(
                code="OPEN_NOTIFICATION_FOR_TERMINAL_TASK",
                severity="medium",
                title="Offene Fortschrittsmeldung für abgeschlossenen Task",
                message=f"Benachrichtigung #{notification.id} ist noch offen, obwohl Task #{notification.task_local_id} terminal ist.",
                entity_type="status_notifications",
                entity_id=notification.id,
                details={"task_local_id": notification.task_local_id, "status": notification.status, "event_type": notification.event_type},
                repairable=True,
                repair_action="complete_terminal_task_notification",
            ))

    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(
        check_id,
        limited,
        summary={
            "active_task_count": sum(1 for task in tasks if str(task.status or "").upper() in ACTIVE_TASK_STATUSES),
            "stale_task_count": len(stale_ids),
            "terminal_without_completed_at_count": len(terminal_without_completed_at_ids),
            "open_terminal_notification_count": len(open_terminal_notification_ids),
            "truncated": truncated,
        },
        repair_plan={
            "stale_task_ids": stale_ids,
            "terminal_task_ids_without_completed_at": terminal_without_completed_at_ids,
            "open_terminal_notification_ids": open_terminal_notification_ids,
        },
    )


def check_storage_references(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:
    check_id = "storage.references"
    settings = get_settings()
    findings: list[dict[str, Any]] = []
    checked = 0
    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all():
        if str(asset.status or "").lower() != "cached":
            continue
        checked += 1
        values = [asset.local_path, asset.filename, asset.public_url]
        resolved = next((resolve_portable_path(value, [settings.audio_storage_path]) for value in values if value), None)
        if not resolved:
            findings.append(_finding(code="CACHED_AUDIO_FILE_MISSING", severity="high", title="Lokale Audiodatei fehlt", message=f"AudioAsset #{asset.id} ist als cached markiert, aber keine lokale Datei ist auflösbar.", entity_type="audio_assets", entity_id=asset.id, details={"local_path": asset.local_path, "filename": asset.filename, "public_url": asset.public_url, "title": asset.display_title or asset.title}))
    for video in db.query(VideoAsset).filter(VideoAsset.is_deleted.is_(False), func.lower(VideoAsset.status) == "cached").all():
        checked += 1
        resolved = next((resolve_portable_path(value, [settings.video_storage_path]) for value in (video.local_path, video.filename, video.public_url) if value), None)
        if not resolved:
            findings.append(_finding(code="CACHED_VIDEO_FILE_MISSING", severity="high", title="Lokale Videodatei fehlt", message=f"VideoAsset #{video.id} ist als cached markiert, aber keine lokale Datei ist auflösbar.", entity_type="video_assets", entity_id=video.id, details={"local_path": video.local_path, "filename": video.filename, "public_url": video.public_url}))
    for transcript in db.query(AudioTranscript).filter(func.lower(AudioTranscript.status).in_(["success", "completed", "done"]), AudioTranscript.srt_path.isnot(None)).all():
        checked += 1
        if not resolve_portable_path(transcript.srt_path, [settings.transcript_storage_path]):
            findings.append(_finding(code="TRANSCRIPT_FILE_MISSING", severity="high", title="SRT-Datei fehlt", message=f"Transcript #{transcript.id} ist erfolgreich, aber die SRT-Datei fehlt.", entity_type="audio_transcripts", entity_id=transcript.id, details={"audio_asset_id": transcript.audio_asset_id, "srt_path": transcript.srt_path}))
    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(check_id, limited, summary={"checked_references": checked, "truncated": truncated})


def check_runtime_configuration(db: Session, parameters: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    check_id = "runtime.configuration"
    settings = get_settings()
    findings: list[dict[str, Any]] = []
    if not str(settings.jwt_secret_key or "").strip():
        findings.append(_finding(code="JWT_SECRET_MISSING", severity="critical", title="JWT-Secret fehlt", message="JWT_SECRET_KEY ist nicht konfiguriert."))
    if not str(settings.database_url or "").strip():
        findings.append(_finding(code="DATABASE_URL_MISSING", severity="critical", title="Datenbank-URL fehlt", message="DATABASE_URL ist leer."))
    if not str(settings.suno_api_key or "").strip() and not bool(settings.suno_opencli_enabled):
        findings.append(_finding(code="SUNO_PROVIDER_UNCONFIGURED", severity="high", title="Suno-Provider nicht konfiguriert", message="Weder SUNO_API_KEY noch OpenCLI ist aktiviert."))
    if settings.enterprise_mode and settings.trusted_hosts_list == ["*"]:
        findings.append(_finding(
            code="TRUSTED_HOSTS_WILDCARD",
            severity="high",
            title="Trusted Hosts zu weit gefasst",
            message="Im Enterprise-Modus ist TRUSTED_HOSTS='*' gesetzt.",
            details={
                "setting": "TRUSTED_HOSTS",
                "current_value": "*",
                "app_env": settings.app_env,
                "enterprise_mode": bool(settings.enterprise_mode),
            },
        ))
    if str(settings.public_base_url or "").startswith("http://localhost") and settings.app_env not in {"local", "dev", "development", "test"}:
        findings.append(_finding(code="PUBLIC_BASE_URL_LOCALHOST", severity="high", title="Öffentliche Basis-URL zeigt auf localhost", message=f"PUBLIC_BASE_URL={settings.public_base_url}"))

    directories = {
        "audio": settings.audio_storage_path,
        "covers": settings.cover_storage_path,
        "videos": settings.video_storage_path,
        "transcripts": settings.transcript_storage_path,
        "backups": settings.backup_storage_path,
    }
    for label, path in directories.items():
        if not path.exists():
            findings.append(_finding(code="STORAGE_DIRECTORY_MISSING", severity="high", title="Storage-Verzeichnis fehlt", message=f"{label}: {path}", entity_type="directory", entity_id=label))
        elif not path.is_dir():
            findings.append(_finding(code="STORAGE_PATH_NOT_DIRECTORY", severity="critical", title="Storage-Pfad ist kein Verzeichnis", message=f"{label}: {path}", entity_type="directory", entity_id=label))
        elif not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            findings.append(_finding(code="STORAGE_DIRECTORY_NOT_WRITABLE", severity="critical", title="Storage-Verzeichnis nicht beschreibbar", message=f"{label}: {path}", entity_type="directory", entity_id=label))

    for binary, required in (("ffmpeg", True), ("ffprobe", True), (str(settings.suno_opencli_binary or "opencli"), bool(settings.suno_opencli_enabled))):
        if required and not shutil.which(binary):
            findings.append(_finding(code="RUNTIME_BINARY_MISSING", severity="high", title="Laufzeitprogramm fehlt", message=f"Erforderliches Programm nicht gefunden: {binary}", entity_type="binary", entity_id=binary))

    limited, truncated = _limit_findings(findings, parameters)
    return _check_result(check_id, limited, summary={"app_env": settings.app_env, "enterprise_mode": settings.enterprise_mode, "truncated": truncated})


CHECK_HANDLERS: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {
    "database.integrity": check_database_integrity,
    "database.references": check_database_references,
    "imports.provenance": check_import_provenance,
    "workflow.tasks": check_workflow_tasks,
    "storage.references": check_storage_references,
    "runtime.configuration": check_runtime_configuration,
}


def _fingerprint(check_ids: list[str], results: list[dict[str, Any]], parameters: dict[str, Any]) -> str:
    repair_basis = [{"check_id": item["check_id"], "repair_plan": item.get("repair_plan") or {}} for item in results]
    raw = json.dumps({"check_ids": check_ids, "repair_basis": repair_basis, "parameters": parameters}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_audit_checks(db: Session, check_ids: list[str], parameters: dict[str, Any] | None = None, *, progress: Callable[[int, str], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    parameters = dict(parameters or {})
    selected = normalize_check_ids(check_ids)
    results: list[dict[str, Any]] = []
    for index, check_id in enumerate(selected, start=1):
        if cancelled and cancelled():
            break
        if progress:
            progress(int(((index - 1) / max(1, len(selected))) * 100), AUDIT_CHECKS[check_id]["title"])
        results.append(CHECK_HANDLERS[check_id](db, parameters))
    findings = [finding for result in results for finding in result.get("findings") or []]
    max_severity = _max_severity(findings)
    report = {
        "version": "maintenance-audit-v1",
        "mode": "dry_run",
        "generated_at": utc_now_naive().isoformat(),
        "check_ids": selected,
        "parameters": parameters,
        "status": "CANCELLED" if cancelled and cancelled() else "SUCCESS",
        "max_severity": max_severity,
        "counts": _counts(findings),
        "problem_type_count": _problem_type_count(results),
        "finding_count": len(findings),
        "repairable_count": sum(1 for item in findings if item.get("repairable")),
        "results": results,
    }
    report["fingerprint"] = _fingerprint(selected, results, parameters)
    return report


def _write_report(task_id: int, report: dict[str, Any], kind: str = "audit") -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"{kind}_{task_id}_{utc_now_naive().strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _run_audit_worker(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if not task:
            return
        mark_task_started(db, task, payload={"phase": "audit"})
        request = _safe_dict(task.request_payload)

        def update(percent: int, label: str) -> None:
            row = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
            if row:
                row.progress = max(0, min(100, int(percent)))
                db.add(row)
            heartbeat_task(db, row or task_id, progress={"percent": percent, "phase": label, "updated_at": utc_now_naive().isoformat()})

        report = run_audit_checks(db, request.get("check_ids") or [], request.get("parameters") or {}, progress=update, cancelled=lambda: is_cancel_requested(db, task_id))
        path = _write_report(task_id, report)
        report["report_path"] = to_portable_path(path, storage_root=project_root() / "storage")
        status = "CANCELLED" if report.get("status") == "CANCELLED" else "SUCCESS"
        final_task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if final_task:
            final_task.progress = 100
            db.add(final_task)
        mark_task_finished(db, task_id, status=status, message="Audit abgebrochen." if status == "CANCELLED" else f"Audit abgeschlossen: {report['finding_count']} Befund(e).", result_payload=report, response_payload={"progress": {"percent": 100, "phase": "Abgeschlossen"}}, notify=True)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        mark_task_finished(db, task_id, status="FAILED", message=f"Audit fehlgeschlagen: {exc}", result_payload={"error": f"{exc.__class__.__name__}: {exc}"}, notify=True)
    finally:
        db.close()


def start_audit_task(db: Session, check_ids: list[str], parameters: dict[str, Any] | None = None) -> SunoTask:
    selected = normalize_check_ids(check_ids)
    task = SunoTask(task_type="maintenance_audit", status="QUEUED", progress=0, request_payload={"local_task": True, "background": True, "mode": "dry_run", "check_ids": selected, "parameters": dict(parameters or {})}, response_payload={"background": True, "status": "QUEUED", "progress": {"percent": 0, "phase": "Warteschlange"}})
    db.add(task)
    db.flush()
    db.add(StatusNotification(event_type="maintenance_audit_started", title="Audit gestartet", message=f"{len(selected)} Prüfung(en) wurden gestartet.", severity="info", status="unread", task_local_id=task.id, content_type="maintenance_audit", content_id=task.id, target_tab="audit", target_payload={"task_local_id": task.id, "target_tab": "audit", "status": "QUEUED"}))
    db.add(ActivityLog(action="maintenance_audit_started", content_type="maintenance_audit", content_id=task.id, new_value={"check_ids": selected, "parameters": dict(parameters or {})}))
    db.commit()
    db.refresh(task)
    run_detached_background(f"maintenance-audit-{task.id}", _run_audit_worker, task.id, finalize_task_id=task.id)
    return task


def _sqlite_backup_for_repair(task_id: int) -> str:
    settings = get_settings()
    bind_url = str(settings.database_url or "")
    if not bind_url.startswith("sqlite"):
        raise RuntimeError("Reparaturen benötigen im MVP eine SQLite-Datenbank mit automatisch erzeugbarem Backup.")
    source_path = Path(str(SessionLocal.kw.get("bind").url.database)).resolve()
    if not source_path.exists():
        raise RuntimeError(f"SQLite-Datenbank nicht gefunden: {source_path}")
    target = settings.backup_storage_path / f"before_audit_repair_{task_id}_{utc_now_naive().strftime('%Y%m%dT%H%M%SZ')}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(source_path), timeout=60)
    destination = sqlite3.connect(str(target), timeout=60)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return str(target)


def _clean_metadata_provenance(value: Any) -> tuple[dict[str, Any], bool]:
    metadata = _safe_dict(value)
    changed = False
    if str(metadata.get("source") or "").strip().lower() == "manual_sunoapi_import":
        metadata.pop("source", None)
        changed = True
    request = metadata.get("request_payload")
    if isinstance(request, dict):
        cleaned = strip_manual_sunoapi_import_source(request)
        if cleaned != request:
            metadata["request_payload"] = cleaned
            changed = True
    return metadata, changed


def _apply_provenance(db: Session, task_ids: list[int]) -> dict[str, Any]:
    changed = {"suno_tasks": 0, "songs": 0, "audio_assets": 0, "video_assets": 0}
    for task_id in task_ids:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id), SunoTask.is_deleted.is_(False)).first()
        if not task or not has_false_manual_sunoapi_import_marker(task_type=task.task_type, request_payload=task.request_payload, response_payload=task.response_payload):
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Task #{task_id} ist kein bestätigter Kandidat mehr.")
        task.request_payload = strip_manual_sunoapi_import_source(task.request_payload)
        db.add(task)
        changed["suno_tasks"] += 1
        for song in db.query(Song).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).all():
            cleaned, did_change = _clean_metadata_provenance(song.metadata_json)
            if did_change:
                song.metadata_json = cleaned
                db.add(song)
                changed["songs"] += 1
        for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False), ((AudioAsset.task_local_id == task.id) | (AudioAsset.suno_task_id == task.task_id))).all():
            cleaned, did_change = _clean_metadata_provenance(asset.metadata_json)
            if did_change:
                asset.metadata_json = cleaned
                db.add(asset)
                changed["audio_assets"] += 1
        for video in db.query(VideoAsset).filter(VideoAsset.is_deleted.is_(False), ((VideoAsset.task_local_id == task.id) | (VideoAsset.suno_task_id == task.task_id))).all():
            cleaned, did_change = _clean_metadata_provenance(video.metadata_json)
            if did_change:
                video.metadata_json = cleaned
                db.add(video)
                changed["video_assets"] += 1
        db.add(ActivityLog(action="maintenance_repair_import_provenance", content_type="suno_task", content_id=task.id, old_value={"source": "manual_sunoapi_import"}, new_value={"source": None}, metadata_json={"audit_repair": True}))
    db.commit()
    return changed


def _apply_orphan_transcript_archive(db: Session, transcript_ids: list[int]) -> dict[str, Any]:
    changed = 0
    skipped = 0
    for transcript_id in transcript_ids:
        transcript = db.query(AudioTranscript).filter(AudioTranscript.id == int(transcript_id)).first()
        if not transcript:
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Transcript #{transcript_id} existiert nicht mehr.")
        if db.query(AudioAsset.id).filter(AudioAsset.id == transcript.audio_asset_id).first():
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Transcript #{transcript_id} besitzt wieder ein AudioAsset.")
        if str(transcript.status or "").strip().lower() == "archived_orphan":
            skipped += 1
            continue
        old_value = {
            "status": transcript.status,
            "error_message": transcript.error_message,
            "audio_asset_id": transcript.audio_asset_id,
            "srt_path": transcript.srt_path,
        }
        transcript.status = "archived_orphan"
        note = f"Archiviert durch Audit-Reparatur: AudioAsset #{transcript.audio_asset_id} fehlt."
        transcript.error_message = f"{transcript.error_message}\n{note}".strip() if transcript.error_message else note
        db.add(transcript)
        db.add(ActivityLog(
            action="maintenance_repair_archive_orphan_transcript",
            content_type="audio_transcript",
            content_id=transcript.id,
            old_value=old_value,
            new_value={"status": transcript.status, "error_message": transcript.error_message},
            metadata_json={"audit_repair": True, "file_deleted": False},
        ))
        changed += 1
    db.commit()
    return {"archived": changed, "already_archived": skipped, "files_deleted": 0}


def _apply_task_completion_backfill(db: Session, task_ids: list[int]) -> dict[str, Any]:
    changed = 0
    skipped = 0
    by_source: dict[str, int] = {}
    for task_id in task_ids:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id), SunoTask.is_deleted.is_(False)).first()
        if not task:
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Task #{task_id} existiert nicht mehr.")
        status = str(task.status or "").upper()
        if status not in TERMINAL_TASK_STATUSES:
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Task #{task_id} ist nicht mehr terminal.")
        if task.completed_at:
            skipped += 1
            continue
        completed_at, source = _best_task_completion_timestamp(task)
        task.completed_at = completed_at
        db.add(task)
        db.add(ActivityLog(
            action="maintenance_repair_task_completed_at",
            content_type="suno_task",
            content_id=task.id,
            old_value={"completed_at": None, "status": status},
            new_value={"completed_at": completed_at.isoformat(), "timestamp_source": source},
            metadata_json={"audit_repair": True},
        ))
        by_source[source] = by_source.get(source, 0) + 1
        changed += 1
    db.commit()
    return {"backfilled": changed, "already_completed": skipped, "timestamp_sources": by_source}


def _apply_terminal_notifications(db: Session, notification_ids: list[int]) -> dict[str, Any]:
    changed = 0
    skipped = 0
    for notification_id in notification_ids:
        notification = db.query(StatusNotification).filter(
            StatusNotification.id == int(notification_id),
            StatusNotification.is_deleted.is_(False),
        ).first()
        if not notification:
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Benachrichtigung #{notification_id} existiert nicht mehr.")
        task = db.query(SunoTask).filter(SunoTask.id == notification.task_local_id, SunoTask.is_deleted.is_(False)).first()
        if not task or str(task.status or "").upper() not in TERMINAL_TASK_STATUSES:
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Zugehöriger Task für Benachrichtigung #{notification_id} ist nicht terminal.")
        if not _is_progress_notification_event(notification.event_type):
            raise RuntimeError(f"Dry-Run nicht mehr aktuell: Benachrichtigung #{notification_id} ist keine Start-/Fortschrittsmeldung.")
        if notification.completed_at or str(notification.status or "").lower() == "done":
            skipped += 1
            continue
        completed_at = task.completed_at or _best_task_completion_timestamp(task)[0]
        old_value = {"status": notification.status, "completed_at": None}
        notification.status = "done"
        notification.completed_at = completed_at
        db.add(notification)
        db.add(ActivityLog(
            action="maintenance_repair_terminal_notification",
            content_type="status_notification",
            content_id=notification.id,
            old_value=old_value,
            new_value={"status": "done", "completed_at": completed_at.isoformat()},
            metadata_json={"audit_repair": True, "task_local_id": task.id},
        ))
        changed += 1
    db.commit()
    return {"completed": changed, "already_completed": skipped}


def _available_repair_actions(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for check in report.get("results") or []:
        for finding in check.get("findings") or []:
            action = str(finding.get("repair_action") or "").strip()
            if finding.get("repairable") and action and action not in result:
                result.append(action)
    return result


def _run_repair_worker(task_id: int, source_audit_task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        source = db.query(SunoTask).filter(SunoTask.id == int(source_audit_task_id), SunoTask.task_type == "maintenance_audit").first()
        if not task or not source or not isinstance(source.result_payload, dict):
            raise RuntimeError("Audit-Quelle nicht gefunden.")
        mark_task_started(db, task, payload={"phase": "repair", "source_audit_task_id": source_audit_task_id})
        task.progress = 10
        db.add(task)
        heartbeat_task(db, task, progress={"percent": 10, "phase": "Dry-Run erneut prüfen"})
        original = source.result_payload
        current = run_audit_checks(db, original.get("check_ids") or [], original.get("parameters") or {})
        if current.get("fingerprint") != original.get("fingerprint"):
            raise RuntimeError("Dry-Run ist nicht mehr aktuell. Bitte Audit erneut ausführen.")
        selected_actions = [
            str(item).strip()
            for item in _safe_dict(task.request_payload).get("repair_actions", [])
            if str(item).strip()
        ]
        available_actions = _available_repair_actions(original)
        if not selected_actions:
            selected_actions = available_actions
        unknown_actions = sorted(set(selected_actions) - set(available_actions))
        if unknown_actions:
            raise RuntimeError(f"Unbekannte oder nicht mehr verfügbare Reparaturaktionen: {', '.join(unknown_actions)}")
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if task:
            task.progress = 35
            db.add(task)
            heartbeat_task(db, task, progress={"percent": 35, "phase": "Datenbank-Backup erstellen"})
        backup_path = _sqlite_backup_for_repair(task_id)
        results: dict[str, Any] = {
            "backup_path": backup_path,
            "source_audit_task_id": source_audit_task_id,
            "selected_repair_actions": selected_actions,
            "actions": {},
        }
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if task:
            task.progress = 55
            db.add(task)
            heartbeat_task(db, task, progress={"percent": 55, "phase": "Reparaturen anwenden"})
        for check in original.get("results") or []:
            check_id = check.get("check_id")
            plan = check.get("repair_plan") or {}
            if check_id == "imports.provenance" and plan.get("candidate_task_ids") and "remove_false_manual_sunoapi_import_marker" in selected_actions:
                results["actions"][check_id] = _apply_provenance(db, [int(item) for item in plan["candidate_task_ids"]])
            elif check_id == "database.references" and plan.get("orphan_transcript_ids") and "archive_orphan_transcript" in selected_actions:
                results["actions"].setdefault(check_id, {})["archive_orphan_transcript"] = _apply_orphan_transcript_archive(db, [int(item) for item in plan["orphan_transcript_ids"]])
            elif check_id == "workflow.tasks":
                workflow_actions: dict[str, Any] = {}
                if plan.get("stale_task_ids") and "recover_stale_task" in selected_actions:
                    workflow_actions["recover_stale_task"] = recover_stale_tasks(db, local_only=True, dry_run=False, task_ids=[int(item) for item in plan["stale_task_ids"]])
                if plan.get("terminal_task_ids_without_completed_at") and "backfill_task_completed_at" in selected_actions:
                    workflow_actions["backfill_task_completed_at"] = _apply_task_completion_backfill(db, [int(item) for item in plan["terminal_task_ids_without_completed_at"]])
                if plan.get("open_terminal_notification_ids") and "complete_terminal_task_notification" in selected_actions:
                    workflow_actions["complete_terminal_task_notification"] = _apply_terminal_notifications(db, [int(item) for item in plan["open_terminal_notification_ids"]])
                if workflow_actions:
                    results["actions"][check_id] = workflow_actions
        results["repair_summary"] = _repair_result_summary(results["actions"], selected_actions)
        path = _write_report(task_id, results, kind="repair")
        results["report_path"] = to_portable_path(path, storage_root=project_root() / "storage")
        db.add(ActivityLog(action="maintenance_repair_applied", content_type="maintenance_repair", content_id=task_id, new_value={"source_audit_task_id": source_audit_task_id, "backup_path": backup_path, "actions": results["actions"]}))
        db.commit()
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
        if task:
            task.progress = 100
            db.add(task)
        mark_task_finished(db, task_id, status="SUCCESS", message="Ausgewählte sichere Reparaturen wurden angewendet.", result_payload=results, response_payload={"progress": {"percent": 100, "phase": "Abgeschlossen"}}, notify=True)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        mark_task_finished(db, task_id, status="FAILED", message=f"Reparatur fehlgeschlagen: {exc}", result_payload={"error": f"{exc.__class__.__name__}: {exc}"}, notify=True)
    finally:
        db.close()


def start_repair_task(db: Session, source_audit_task_id: int, *, repair_actions: list[str] | None = None) -> SunoTask:
    source = db.query(SunoTask).filter(SunoTask.id == int(source_audit_task_id), SunoTask.task_type == "maintenance_audit", SunoTask.is_deleted.is_(False)).first()
    if not source or str(source.status or "").upper() != "SUCCESS" or not isinstance(source.result_payload, dict):
        raise ValueError("Nur ein erfolgreich abgeschlossener Audit-Dry-Run kann angewendet werden.")
    if int(source.result_payload.get("repairable_count") or 0) <= 0:
        raise ValueError("Dieser Audit-Lauf enthält keine sicheren Reparaturvorschläge.")
    available_actions = _available_repair_actions(source.result_payload)
    selected_actions = [str(item).strip() for item in (repair_actions or []) if str(item).strip()]
    if not selected_actions:
        selected_actions = available_actions
    unknown_actions = sorted(set(selected_actions) - set(available_actions))
    if unknown_actions:
        raise ValueError(f"Nicht verfügbare Reparaturaktionen: {', '.join(unknown_actions)}")
    if not selected_actions:
        raise ValueError("Es wurde keine Reparaturaktion ausgewählt.")
    task = SunoTask(task_type="maintenance_repair", status="QUEUED", progress=0, request_payload={"local_task": True, "background": True, "source_audit_task_id": source.id, "fingerprint": source.result_payload.get("fingerprint"), "repair_actions": selected_actions}, response_payload={"background": True, "status": "QUEUED", "progress": {"percent": 0, "phase": "Warteschlange"}})
    db.add(task)
    db.flush()
    db.add(StatusNotification(event_type="maintenance_repair_started", title="Reparatur gestartet", message=f"Audit-Lauf #{source.id} wird nach erneuter Prüfung angewendet.", severity="warning", status="unread", task_local_id=task.id, content_type="maintenance_repair", content_id=task.id, target_tab="audit", target_payload={"task_local_id": task.id, "source_audit_task_id": source.id, "target_tab": "audit"}))
    db.commit()
    db.refresh(task)
    run_detached_background(f"maintenance-repair-{task.id}", _run_repair_worker, task.id, source.id, finalize_task_id=task.id)
    return task


def serialize_audit_task(task: SunoTask, *, include_result: bool = True) -> dict[str, Any]:
    full_result_payload = task.result_payload or {}
    result_payload = full_result_payload
    if isinstance(full_result_payload, dict):
        if task.task_type == "maintenance_audit" and "problem_type_count" not in full_result_payload:
            full_result_payload = {
                **full_result_payload,
                "problem_type_count": _problem_type_count(full_result_payload.get("results") or []),
            }
        elif task.task_type == "maintenance_repair" and "repair_summary" not in full_result_payload:
            full_result_payload = {
                **full_result_payload,
                "repair_summary": _repair_result_summary(
                    _safe_dict(full_result_payload.get("actions")),
                    list(full_result_payload.get("selected_repair_actions") or []),
                ),
            }
        result_payload = full_result_payload
    if not include_result and isinstance(result_payload, dict):
        result_payload = {
            key: result_payload.get(key)
            for key in (
                "version",
                "mode",
                "status",
                "max_severity",
                "counts",
                "problem_type_count",
                "finding_count",
                "repairable_count",
                "report_path",
                "source_audit_task_id",
                "selected_repair_actions",
                "repair_summary",
                "backup_path",
            )
            if key in result_payload
        }
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "request_payload": task.request_payload or {},
        "response_payload": task.response_payload or {},
        "result_payload": result_payload,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "cancel_requested": bool(task.cancel_requested),
    }
