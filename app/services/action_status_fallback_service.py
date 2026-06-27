from __future__ import annotations

"""Fallback-Statusmeldungen fuer schreibende API-Aktionen.

Diese Schicht ist absichtlich defensiv: Fachfunktionen sollen weiterhin ihre
eigenen detaillierten SunoTask-/StatusNotification-Eintraege erzeugen. Der
Fallback greift nur, wenn ein erfolgreicher POST/PUT/PATCH/DELETE-Request sonst
keinen Statusbericht angelegt hat. So bleiben bestehende Prozessablaeufe stabil,
waehrend neue oder vergessene Endpunkte trotzdem auf /status sichtbar werden.
"""

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import StatusNotification, SunoTask
from app.services.system_status_notification_service import create_system_status_notification


TRACKED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXCLUDED_PREFIXES = (
    "/api/notifications",
    "/api/webhooks",
)
EXCLUDED_EXACT_PATHS = {
    "/api/music/tasks/refresh-pending",
    "/api/assistant/actions/preview",
    "/api/daw/commands/resolve",
}
EXCLUDED_PATTERNS = (
    re.compile(r"^/api/music/tasks/\d+/refresh$"),
)


@dataclass(frozen=True)
class ActionStatusMarker:
    latest_notification_id: int
    latest_task_id: int


def should_track_api_action(method: str, path: str) -> bool:
    method = str(method or "").upper()
    clean_path = str(path or "").split("?", 1)[0].rstrip("/") or "/"
    if method not in TRACKED_METHODS:
        return False
    if not clean_path.startswith("/api/"):
        return False
    if clean_path in EXCLUDED_EXACT_PATHS:
        return False
    if any(clean_path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if any(pattern.match(clean_path) for pattern in EXCLUDED_PATTERNS):
        return False
    return True


def snapshot_action_status_marker(db: Session) -> ActionStatusMarker | None:
    try:
        latest_notification_id = db.query(func.max(StatusNotification.id)).scalar() or 0
        latest_task_id = db.query(func.max(SunoTask.id)).scalar() or 0
        return ActionStatusMarker(int(latest_notification_id), int(latest_task_id))
    except Exception:
        return None


def has_action_status_since(db: Session, marker: ActionStatusMarker | None) -> bool:
    if marker is None:
        return True
    try:
        notification_exists = (
            db.query(StatusNotification.id)
            .filter(StatusNotification.id > marker.latest_notification_id)
            .first()
            is not None
        )
        if notification_exists:
            return True
        task_exists = db.query(SunoTask.id).filter(SunoTask.id > marker.latest_task_id).first() is not None
        return bool(task_exists)
    except Exception:
        return True


def _compact_label(value: str) -> str:
    text = str(value or "").strip().strip("/")
    text = re.sub(r"[^a-zA-Z0-9_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "API-Aktion"


def _infer_action_label(method: str, path: str) -> str:
    clean_path = str(path or "").split("?", 1)[0].rstrip("/")
    parts = [part for part in clean_path.split("/") if part and not part.isdigit()]
    tail = " ".join(parts[-3:]).replace("-", " ").replace("_", " ")
    verb = {
        "POST": "ausgefuehrt",
        "PUT": "aktualisiert",
        "PATCH": "aktualisiert",
        "DELETE": "geloescht",
    }.get(str(method or "").upper(), "ausgefuehrt")
    return f"{_compact_label(tail).title()} {verb}"


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item > 0:
            return item
    return None


def _payload_value(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = _payload_value(value, *keys)
            if nested not in (None, ""):
                return nested
    return None


def _infer_target(path: str, response_payload: Any, path_params: dict[str, Any] | None) -> tuple[str, str, int | None, dict[str, Any]]:
    clean_path = str(path or "").split("?", 1)[0].rstrip("/") or "/"
    params = path_params or {}
    payload = response_payload if isinstance(response_payload, dict) else {}
    target_tab = "status"
    content_type = "api_action"
    content_id: int | None = None

    audio_id = _first_int(
        params.get("asset_id"),
        params.get("audio_asset_id"),
        _payload_value(payload, "audio_asset_id", "asset_id", "audioAssetId"),
    )
    song_id = _first_int(params.get("song_id"), _payload_value(payload, "song_id", "songId"))
    style_id = _first_int(params.get("style_id"), _payload_value(payload, "style_id"))
    playlist_id = _first_int(params.get("playlist_id"), _payload_value(payload, "playlist_id"))
    lyric_id = _first_int(params.get("draft_id"), _payload_value(payload, "draft_id", "lyric_id"))
    generic_id = _first_int(params.get("item_id"), params.get("id"), _payload_value(payload, "id"))
    task_id = _first_int(_payload_value(payload, "task_local_id", "local_task_id"))

    if clean_path.startswith(("/api/audio-assets", "/api/archive/audio")):
        target_tab = "library"
        content_type = "audio"
        content_id = audio_id or generic_id
    elif clean_path.startswith("/api/library/styles"):
        target_tab = "styles"
        content_type = "style"
        content_id = style_id or generic_id
    elif clean_path.startswith("/api/library/playlists"):
        target_tab = "playlists"
        content_type = "playlist"
        content_id = playlist_id or generic_id
    elif clean_path.startswith("/api/library/lyrics"):
        target_tab = "texts"
        content_type = "lyric"
        content_id = lyric_id or generic_id
    elif clean_path.startswith("/api/library/content"):
        target_tab = "library"
        content_type = str(params.get("content_type") or _payload_value(payload, "content_type") or "library")
        content_id = generic_id
    elif clean_path.startswith("/api/music/songs"):
        target_tab = "library"
        content_type = "song"
        content_id = song_id or generic_id
    elif clean_path.startswith("/api/music/voices"):
        target_tab = "music"
        content_type = "voice"
        content_id = generic_id
    elif clean_path.startswith("/api/music"):
        target_tab = "status"
        content_type = "task_status"
        content_id = task_id or generic_id
    elif clean_path.startswith("/api/production"):
        target_tab = "production"
        content_type = "production"
        content_id = audio_id or generic_id
    elif clean_path.startswith("/api/daw"):
        target_tab = "daw"
        content_type = "daw"
        content_id = audio_id or generic_id
    elif clean_path.startswith("/api/admin"):
        target_tab = "admin"
        content_type = "admin"
        content_id = generic_id
    elif clean_path.startswith("/api/system"):
        target_tab = "system"
        content_type = "system"
        content_id = generic_id
    elif clean_path.startswith("/api/files"):
        target_tab = "system"
        content_type = "file"
        content_id = generic_id
    elif clean_path.startswith("/api/ai-chat"):
        target_tab = "lyrics"
        content_type = "ai_chat"
        content_id = generic_id

    target_payload = {
        "target_tab": target_tab,
        "path": clean_path,
        "content_type": content_type,
        "status": "SUCCESS",
    }
    if audio_id:
        target_payload["audio_asset_id"] = audio_id
    if song_id:
        target_payload["song_id"] = song_id
    if style_id:
        target_payload["style_id"] = style_id
    if playlist_id:
        target_payload["playlist_id"] = playlist_id
    if task_id:
        target_payload["task_local_id"] = task_id
    return target_tab, content_type, content_id, target_payload


def create_action_status_fallback(
    db: Session,
    *,
    method: str,
    path: str,
    status_code: int,
    response_payload: Any = None,
    path_params: dict[str, Any] | None = None,
) -> StatusNotification | None:
    target_tab, content_type, content_id, target_payload = _infer_target(path, response_payload, path_params)
    target_payload["method"] = str(method or "").upper()
    target_payload["status_code"] = int(status_code or 0)

    return create_system_status_notification(
        db,
        event_type="api_action_completed",
        title=f"Aktion abgeschlossen: {_infer_action_label(method, path)}",
        message="Die ausgefuehrte Funktion wurde erfolgreich abgeschlossen.",
        severity="success",
        target_tab=target_tab,
        target_payload=target_payload,
        content_type=content_type,
        content_id=content_id,
        commit=True,
    )
