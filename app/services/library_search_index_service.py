from __future__ import annotations

"""Zentrale, manuell bedienbare Verwaltung des Library-Suchindex.

Der Suchindex bleibt Teil von ``AudioAsset.metadata_json['ai_tags']``.
Dieses Modul liest und ändert ausschließlich dieses Unterobjekt sowie passende
ActivityLog-Einträge. Audio-, Import-, Song-, SRT-, DAW- und Taskdaten werden
nicht verändert.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import ActivityLog, AudioAsset, SunoTask
from app.services.library_ai_tagging_service import (
    BULK_TAGGING_TASK_TYPE,
    TAGGING_METADATA_KEY,
    TAGGING_TASK_TYPE,
    TAGGING_VERSION,
    has_library_ai_tag_content,
    load_library_ai_tagging_settings,
    normalize_ai_tags,
    read_saved_library_ai_tags,
)
from app.services.task_lifecycle_service import is_active_status
from app.utils.time_utils import utc_now_naive

TAGGING_TASK_TYPES = {TAGGING_TASK_TYPE, BULK_TAGGING_TASK_TYPE}
FAILED_TASK_STATUSES = {"FAILED", "ERROR", "PARTIAL_SUCCESS"}


def _positive_ids(values: Iterable[Any]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        result.append(number)
    return result


def task_audio_asset_ids(task: SunoTask | None) -> list[int]:
    if not task or str(task.task_type or "").strip() not in TAGGING_TASK_TYPES:
        return []
    payload = task.request_payload if isinstance(task.request_payload, dict) else {}
    values: list[Any] = []
    if isinstance(payload.get("audio_asset_ids"), list):
        values.extend(payload.get("audio_asset_ids") or [])
    if payload.get("audio_asset_id") is not None:
        values.append(payload.get("audio_asset_id"))
    return _positive_ids(values)


def latest_library_tagging_tasks_by_asset(db: Session) -> dict[int, SunoTask]:
    """Liefert pro Asset den jüngsten Tagging-Task, ohne Datensätze zu ändern."""
    rows = (
        db.query(SunoTask)
        .filter(
            SunoTask.task_type.in_(TAGGING_TASK_TYPES),
            SunoTask.is_deleted.is_(False),
        )
        .order_by(SunoTask.id.desc())
        .all()
    )
    result: dict[int, SunoTask] = {}
    for task in rows:
        for asset_id in task_audio_asset_ids(task):
            result.setdefault(asset_id, task)
    return result


def active_library_tagging_tasks_by_asset(db: Session) -> dict[int, SunoTask]:
    rows = (
        db.query(SunoTask)
        .filter(
            SunoTask.task_type.in_(TAGGING_TASK_TYPES),
            SunoTask.is_deleted.is_(False),
        )
        .order_by(SunoTask.id.desc())
        .all()
    )
    result: dict[int, SunoTask] = {}
    for task in rows:
        if not is_active_status(task.status):
            continue
        for asset_id in task_audio_asset_ids(task):
            result.setdefault(asset_id, task)
    return result


def _task_status_for_asset(saved: dict[str, Any] | None, task: SunoTask | None) -> str:
    if task and is_active_status(task.status):
        return "running"
    if has_library_ai_tag_content(saved):
        return "present"
    if task and str(task.status or "").strip().upper() in FAILED_TASK_STATUSES:
        return "failed"
    return "missing"


def _public_index_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    public = {key: item for key, item in value.items() if key != "raw_response"}
    return public


def _audit_index_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: value.get(key)
        for key in ("version", "tags", "moods", "genres", "language", "confidence", "reason", "source", "generated_at", "updated_at")
        if value.get(key) is not None
    }


def _task_payload(task: SunoTask | None) -> dict[str, Any] | None:
    if not task:
        return None
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "error_message": task.error_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _asset_title(asset: AudioAsset) -> str:
    return str(asset.display_title or asset.title or asset.filename or f"Audio #{asset.id}").strip()


def _search_text(asset: AudioAsset, saved: dict[str, Any] | None) -> str:
    values: list[Any] = [
        asset.id,
        asset.audio_id,
        asset.suno_task_id,
        asset.display_title,
        asset.title,
        asset.filename,
        asset.version_label,
    ]
    if isinstance(saved, dict):
        for key in ("tags", "moods", "genres"):
            if isinstance(saved.get(key), list):
                values.extend(saved.get(key) or [])
        values.extend([saved.get("language"), saved.get("provider"), saved.get("model")])
    return " ".join(str(value or "") for value in values).lower()


def list_library_search_index(
    db: Session,
    *,
    search: str = "",
    status: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    page = max(1, int(page or 1))
    page_size = max(10, min(200, int(page_size or 50)))
    normalized_status = str(status or "all").strip().lower()
    if normalized_status not in {"all", "present", "missing", "running", "failed"}:
        normalized_status = "all"
    needle = str(search or "").strip().lower()

    assets = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.updated_at.desc(), AudioAsset.id.desc())
        .all()
    )
    task_map = latest_library_tagging_tasks_by_asset(db)
    summary = {"all": 0, "present": 0, "missing": 0, "running": 0, "failed": 0}
    records: list[dict[str, Any]] = []

    for asset in assets:
        saved = read_saved_library_ai_tags(asset)
        task = task_map.get(asset.id)
        tag_status = _task_status_for_asset(saved, task)
        summary["all"] += 1
        summary[tag_status] += 1
        if needle and needle not in _search_text(asset, saved):
            continue
        if normalized_status != "all" and tag_status != normalized_status:
            continue
        records.append({
            "audio_asset_id": asset.id,
            "song_id": asset.song_id,
            "audio_id": asset.audio_id,
            "suno_task_id": asset.suno_task_id,
            "title": _asset_title(asset),
            "version_label": asset.version_label,
            "duration_seconds": asset.duration_seconds,
            "audio_local": bool(asset.audio_local),
            "asset_status": asset.status,
            "tag_status": tag_status,
            "ai_tags": _public_index_value(saved),
            "latest_task": _task_payload(task),
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        })

    total = len(records)
    start = (page - 1) * page_size
    items = records[start:start + page_size]
    pages = max(1, (total + page_size - 1) // page_size)
    if page > pages:
        page = pages
        start = (page - 1) * page_size
        items = records[start:start + page_size]

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
        "summary": summary,
        "filters": {"search": search, "status": normalized_status},
    }


def _safe_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def update_library_search_index(
    db: Session,
    asset: AudioAsset,
    *,
    tags: list[str],
    moods: list[str],
    genres: list[str],
    language: str,
    reason: str | None = None,
) -> dict[str, Any]:
    settings = load_library_ai_tagging_settings(db)
    existing = read_saved_library_ai_tags(asset) or {}
    old_value = dict(existing)
    now = utc_now_naive().isoformat()
    normalized_language = str(language or "unknown").strip().lower()[:16] or "unknown"
    payload = {
        **existing,
        "version": str(existing.get("version") or TAGGING_VERSION),
        "tags": normalize_ai_tags(tags, max_tags=int(settings["max_tags"])),
        "moods": normalize_ai_tags(moods, max_tags=3),
        "genres": normalize_ai_tags(genres, max_tags=3),
        "language": normalized_language,
        "confidence": _safe_confidence(existing.get("confidence")),
        "reason": str(reason if reason is not None else existing.get("reason") or "").strip()[:240],
        "generated_at": existing.get("generated_at") or now,
        "updated_at": now,
        "source": "manual_library_search_index",
        "manually_edited": True,
    }
    metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
    metadata[TAGGING_METADATA_KEY] = payload
    asset.metadata_json = metadata
    flag_modified(asset, "metadata_json")
    db.add(asset)
    db.add(ActivityLog(
        action="library_ai_tags_updated",
        content_type="audio_asset",
        content_id=asset.id,
        old_value=_audit_index_value(old_value),
        new_value=_audit_index_value(payload),
        metadata_json={"source": "library_search_index_admin"},
    ))
    db.commit()
    db.refresh(asset)
    return payload


def delete_library_search_index(db: Session, asset: AudioAsset) -> bool:
    metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
    existing = metadata.get(TAGGING_METADATA_KEY)
    if TAGGING_METADATA_KEY not in metadata:
        return False
    metadata.pop(TAGGING_METADATA_KEY, None)
    asset.metadata_json = metadata
    flag_modified(asset, "metadata_json")
    db.add(asset)
    db.add(ActivityLog(
        action="library_ai_tags_deleted",
        content_type="audio_asset",
        content_id=asset.id,
        old_value=_audit_index_value(existing if isinstance(existing, dict) else None),
        new_value=None,
        metadata_json={"source": "library_search_index_admin"},
    ))
    db.commit()
    db.refresh(asset)
    return True
