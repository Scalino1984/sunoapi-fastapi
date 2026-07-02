from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.config import get_settings
from app.services.portable_path_service import public_url_for_file, to_portable_path
from app.models import AudioAsset, AudioProject, AudioTranscript, Song, SunoTask
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.audio_cache_service import parse_source_datetime
from app.services.waveform_service import sanitize_waveform_payload_for_asset
from app.utils.time_utils import utc_now_naive

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
AUDIO_EXTENSIONS_FALLBACK = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
AUDIO_MIME_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-mp3": "audio/mpeg",
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/x-flac": "audio/flac",
}
AUDIO_URL_PREFERENCE = (
    "sourceAudioUrl",
    "source_audio_url",
    "audioUrl",
    "audio_url",
    "sourceStreamAudioUrl",
    "source_stream_audio_url",
    "streamAudioUrl",
    "stream_audio_url",
    "downloadUrl",
    "download_url",
    "mp3Url",
    "mp3_url",
    "wavUrl",
    "wav_url",
)
IMAGE_URL_PREFERENCE = (
    "sourceImageUrl",
    "source_image_url",
    "imageUrl",
    "image_url",
    "coverImageUrl",
    "cover_image_url",
    "thumbnailUrl",
    "thumbnail_url",
)


def _now() -> datetime:
    return utc_now_naive()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _norm(value).lower()


def _url_extension(value: str | None) -> str:
    if not value:
        return ""
    return Path(unquote(urlparse(str(value)).path)).suffix.lower()


def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_image_url(value: Any) -> bool:
    return is_http_url(value) and _url_extension(str(value)) in IMAGE_EXTENSIONS


def is_suno_share_page_url(value: Any) -> bool:
    """Erkennt öffentliche Suno-Seiten, die nicht direkt abspielbar sind.

    Diese Links sehen fachlich wie Song-Links aus, sind aber HTML-Seiten und
    dürfen nicht als AudioAsset.source_url materialisiert werden.
    """
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    host = (parsed.netloc or "").lower().split(":", 1)[0]
    path = (parsed.path or "").lower().rstrip("/")
    return host in {"suno.com", "www.suno.com"} and path.startswith("/song/")


def is_audio_url(value: Any) -> bool:
    if not is_http_url(value):
        return False
    if is_suno_share_page_url(value):
        return False
    url = str(value)
    extension = _url_extension(url)
    if extension in IMAGE_EXTENSIONS:
        return False
    allowed = set(get_settings().audio_allowed_extensions_list) | AUDIO_EXTENSIONS_FALLBACK
    if extension in allowed:
        return True
    lowered = url.lower()
    # Wichtig: "song" allein ist zu breit, weil öffentliche Suno-Seiten
    # wie https://suno.com/song/... sonst fälschlich als Audio gelten.
    return any(marker in lowered for marker in ("audio", "mp3", "wav", "m4a", "flac", "aac", "ogg", "stream", "download"))


def normalize_mime(value: Any, path: Path | None = None) -> str | None:
    raw = _lower(value).split(";", 1)[0].strip()
    if raw in AUDIO_MIME_ALIASES:
        return AUDIO_MIME_ALIASES[raw]
    if raw:
        return raw
    return normalize_audio_content_type(None, path) if path else None


def is_bad_image_asset(asset: AudioAsset) -> bool:
    if is_image_url(asset.source_url):
        return True
    if _lower(asset.content_type).startswith("image/"):
        return True
    if "image/" in _lower(asset.error_message):
        return True
    return False


def _find_local_audio_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    storage_path = settings.audio_storage_path
    root = storage_path.expanduser().resolve()
    candidates: list[Path] = []

    def add(value: Any) -> None:
        if not value:
            return
        text = str(value).strip().split("?", 1)[0]
        if not text:
            return
        parsed = urlparse(text)
        path_text = unquote(parsed.path if parsed.scheme in {"http", "https"} else text)
        candidate = Path(path_text)
        candidates.append(candidate)
        if candidate.name:
            candidates.append(storage_path / candidate.name)
        route = settings.suno_audio_public_route.rstrip("/")
        if route and path_text.startswith(route + "/"):
            rel = path_text[len(route):].lstrip("/")
            if rel and ".." not in Path(rel).parts:
                candidates.append(storage_path / rel)
        marker = "/storage/audio/"
        normalized_path = path_text.replace("\\", "/")
        if marker in normalized_path:
            rel = normalized_path.rsplit(marker, 1)[-1].lstrip("/")
            if rel and ".." not in Path(rel).parts:
                candidates.append(storage_path / rel)

    add(asset.local_path)
    add(asset.filename)
    add(asset.public_url)
    if asset.source_url and not is_image_url(asset.source_url):
        add(asset.source_url)

    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    candidate_meta = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    for source in (metadata, candidate_meta, request_payload):
        for key in AUDIO_URL_PREFERENCE:
            add(source.get(key))

    if storage_path.exists():
        for extension in settings.audio_allowed_extensions_list:
            candidates.extend(sorted(storage_path.glob(f"audio_{asset.id}_*{extension}")))
        if asset.filename:
            candidates.extend(sorted(storage_path.rglob(Path(str(asset.filename)).name)))
        candidates.extend(sorted(storage_path.glob(f"*_{asset.id}_*.mp3")))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).expanduser().resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def repair_local_file_metadata(asset: AudioAsset) -> bool:
    path = _find_local_audio_file(asset)
    if not path:
        return False
    settings = get_settings()
    changed = False
    updates: dict[str, Any] = {
        "status": "cached",
        "local_path": to_portable_path(path, storage_root=settings.audio_storage_path),
        "filename": path.name,
        "public_url": public_url_for_file(path, storage_root=settings.audio_storage_path, public_route=settings.suno_audio_public_route),
        "file_size_bytes": path.stat().st_size,
        "content_type": normalize_audio_content_type(asset.content_type, path),
    }
    duration = read_audio_duration_seconds(path)
    if duration and not asset.duration_seconds:
        # Some Suno MP3 files have misleading headers and browser/native readers
        # may disagree by seconds or minutes. Metadata repair may fill a missing
        # duration, but it must not replace a duration already stored by the app.
        updates["duration_seconds"] = duration
    for key, value in updates.items():
        if getattr(asset, key) != value:
            setattr(asset, key, value)
            changed = True
    if asset.error_message:
        asset.error_message = None
        changed = True
    return changed


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _preferred_audio_url(item: dict[str, Any]) -> str | None:
    for key in AUDIO_URL_PREFERENCE:
        value = item.get(key)
        if isinstance(value, str) and is_audio_url(value):
            return value
    # Fallback only when key semantics are explicit enough.
    for key, value in item.items():
        if not isinstance(value, str):
            continue
        normalized = key.replace("-", "_").lower()
        if "image" in normalized or "cover" in normalized or "thumbnail" in normalized:
            continue
        if normalized in {"url", "src", "href"} and is_audio_url(value):
            return value
    return None


def _preferred_image_url(item: dict[str, Any]) -> str | None:
    for key in IMAGE_URL_PREFERENCE:
        value = item.get(key)
        if isinstance(value, str) and is_http_url(value):
            return value
    for key, value in item.items():
        if isinstance(value, str) and is_image_url(value):
            return value
    return None


def _task_result_suno_items(task: SunoTask) -> list[dict[str, Any]]:
    payloads = [task.result_payload, task.response_payload]
    items: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for item in _walk_dicts(payload):
            if not isinstance(item, dict):
                continue
            if item.get("id") and _preferred_audio_url(item):
                items.append(item)
    # De-duplicate by audio id + preferred URL.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("id") or ""), str(_preferred_audio_url(item) or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _candidate_from_suno_item(task: SunoTask, item: dict[str, Any]) -> dict[str, Any] | None:
    source_url = _preferred_audio_url(item)
    if not source_url:
        return None
    duration = None
    try:
        if item.get("duration") is not None:
            duration = int(round(float(item.get("duration"))))
    except (TypeError, ValueError):
        duration = None
    request_payload = task.request_payload or {}
    return {
        "task_local_id": task.id,
        "suno_task_id": task.task_id,
        "audio_id": str(item.get("id")) if item.get("id") else None,
        "title": item.get("title") or request_payload.get("title"),
        "display_title": item.get("title") or request_payload.get("title"),
        "image_url": _preferred_image_url(item),
        "source_url": source_url,
        "duration_seconds": duration,
        "status": "remote",
        "content_type": "audio/mpeg" if _url_extension(source_url) == ".mp3" else None,
        "operation_label": _operation_label_for_task(task.task_type),
        "parent_audio_id": request_payload.get("audio_id") or request_payload.get("audioId") or item.get("parentAudioId"),
        "parent_task_id": request_payload.get("task_id") or request_payload.get("taskId"),
        "metadata_json": {"candidate": item, "request_payload": request_payload, "operation": _operation_label_for_task(task.task_type)},
    }


def _operation_label_for_task(task_type: str | None) -> str:
    return {
        "generate_music": "Generiert",
        "extend_music": "Extended",
        "upload_and_extend": "Extended",
        "upload_and_cover": "Cover Song",
        "add_vocals": "Add Vocals",
        "add_instrumental": "Add Instrumental",
        "generate_mashup": "Mashup",
        "generate_sounds": "Sound",
        "separate": "Stem Separation",
        "convert_to_wav": "WAV",
        "generate_midi": "MIDI",
        "create_video": "Video",
    }.get(str(task_type or ""), str(task_type or "Audio"))


def _asset_score(asset: AudioAsset) -> int:
    score = 0
    status = _lower(asset.status)
    if status == "cached":
        score += 1000
    elif status in {"remote", "created"}:
        score += 500
    elif status == "failed":
        score -= 500
    # Listen-/Sortierpfade dürfen kein Datei-I/O auslösen. Ein existierender
    # lokaler Pfad wurde beim Cache/Repair geprüft; für Read-Performance reicht
    # hier die gespeicherte Metadatenlage.
    if asset.local_path or asset.filename or asset.public_url:
        score += 300
    if asset.public_url:
        score += 80
    if is_audio_url(asset.source_url):
        score += 80
    if asset.audio_id:
        score += 40
    if asset.image_url:
        score += 20
    if asset.duration_seconds and asset.duration_seconds > 0:
        score += 20
    if is_bad_image_asset(asset):
        score -= 1000
    if _lower(asset.error_message):
        score -= 100
    return score


def _merge_asset_metadata(winner: AudioAsset, loser: AudioAsset) -> bool:
    changed = False
    for field in ("image_url", "title", "display_title", "suno_task_id", "audio_id", "operation_label", "parent_audio_id", "parent_task_id", "version_label"):
        if not getattr(winner, field, None) and getattr(loser, field, None):
            setattr(winner, field, getattr(loser, field))
            changed = True
    if not winner.duration_seconds and loser.duration_seconds:
        winner.duration_seconds = loser.duration_seconds
        changed = True
    if not winner.metadata_json and loser.metadata_json:
        winner.metadata_json = loser.metadata_json
        changed = True
    return changed


def upsert_audio_asset_from_candidate(db: Session, task: SunoTask, item: dict[str, Any]) -> AudioAsset | None:
    data = _candidate_from_suno_item(task, item)
    if not data:
        return None
    audio_id = data.get("audio_id")
    source_url = data["source_url"]
    asset = None
    if audio_id:
        candidates = db.query(AudioAsset).filter(AudioAsset.audio_id == audio_id, AudioAsset.is_deleted.is_(False)).all()
        good_candidates = [row for row in candidates if not is_bad_image_asset(row)]
        if good_candidates:
            asset = sorted(good_candidates, key=_asset_score, reverse=True)[0]
    if asset is None:
        asset = db.query(AudioAsset).filter(AudioAsset.source_url == source_url, AudioAsset.is_deleted.is_(False)).first()
    if asset is None:
        deleted_match = None
        if audio_id:
            deleted_match = db.query(AudioAsset).filter(AudioAsset.audio_id == audio_id, AudioAsset.is_deleted.is_(True)).first()
        if deleted_match is None and source_url:
            deleted_match = db.query(AudioAsset).filter(AudioAsset.source_url == source_url, AudioAsset.is_deleted.is_(True)).first()
        if deleted_match is not None:
            # Benutzer-Löschungen dürfen durch die automatische Reparatur nicht wieder als neue Library-Assets erscheinen.
            return None
        asset = AudioAsset(source_url=source_url)
        db.add(asset)
        db.flush()
    changed = False
    for key, value in data.items():
        if value is None:
            continue
        if key == "metadata_json":
            if not asset.metadata_json:
                asset.metadata_json = value
                changed = True
            continue
        if not getattr(asset, key, None) or key in {"source_url", "status", "content_type"}:
            if getattr(asset, key, None) != value:
                setattr(asset, key, value)
                changed = True
    if repair_local_file_metadata(asset):
        changed = True
    if changed:
        db.add(asset)
    return asset


def quarantine_invalid_audio_assets(db: Session) -> int:
    changed = 0
    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all():
        if is_bad_image_asset(asset):
            asset.is_deleted = True
            asset.deleted_at = _now()
            asset.deleted_reason = "Bereinigt: Bild-URL wurde fälschlich als AudioAsset gespeichert."
            changed += 1
            db.add(asset)
            continue
        content_type = normalize_mime(asset.content_type)
        if content_type and content_type != asset.content_type:
            asset.content_type = content_type
            changed += 1
            db.add(asset)
        if _lower(asset.status) == "failed" and "audio/mp3" in _lower(asset.error_message) and is_audio_url(asset.source_url):
            asset.status = "remote"
            asset.error_message = None
            asset.content_type = "audio/mpeg"
            changed += 1
            db.add(asset)
        if repair_local_file_metadata(asset):
            changed += 1
            db.add(asset)
    return changed


def reconstruct_audio_assets_from_tasks(db: Session) -> int:
    changed = 0
    tasks = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.asc()).all()
    for task in tasks:
        for item in _task_result_suno_items(task):
            before_count = db.query(AudioAsset).count()
            asset = upsert_audio_asset_from_candidate(db, task, item)
            after_count = db.query(AudioAsset).count()
            if asset is not None:
                changed += 1 if after_count != before_count else 0
    return changed


def deduplicate_audio_assets(db: Session) -> int:
    deleted = 0
    groups: dict[str, list[AudioAsset]] = {}
    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all():
        key = asset.audio_id or asset.checksum_sha256 or asset.source_url or f"id:{asset.id}"
        groups.setdefault(str(key), []).append(asset)
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        rows_sorted = sorted(rows, key=_asset_score, reverse=True)
        winner = rows_sorted[0]
        changed_winner = False
        for loser in rows_sorted[1:]:
            if _merge_asset_metadata(winner, loser):
                changed_winner = True
            loser.is_deleted = True
            loser.deleted_at = _now()
            loser.deleted_reason = f"Bereinigt: Duplikat von AudioAsset #{winner.id}."
            db.add(loser)
            deleted += 1
        if changed_winner:
            db.add(winner)
    return deleted


def repair_extend_tasks_with_local_audio_ids(db: Session) -> int:
    updated = 0
    for task in db.query(SunoTask).filter(SunoTask.is_deleted.is_(False), SunoTask.task_type == "extend_music").all():
        payload = dict(task.request_payload or {})
        raw_audio_id = payload.get("audio_id") or payload.get("audioId")
        if raw_audio_id is None:
            continue
        raw_text = str(raw_audio_id)
        if not raw_text.isdigit():
            continue
        asset = db.query(AudioAsset).filter(AudioAsset.id == int(raw_text)).first()
        if not asset or not asset.audio_id:
            continue
        payload["audio_id"] = asset.audio_id
        payload.pop("audioId", None)
        task.request_payload = payload
        if _lower(task.status) in {"pending", "submitted", "processing", "created"}:
            task.error_message = "Diese alte Extension wurde ursprünglich mit lokaler DB-ID statt Suno-Audio-ID gestartet. Payload wurde repariert; bitte bei Bedarf neu starten."
        db.add(task)
        updated += 1
    return updated


PROJECT_TITLE_MARKERS = (" Extended Again", " Extended", " Cover Song", " Cover", " Add Vocals", " Add Instrumental", " Final")


def _base_project_title(asset: AudioAsset) -> str:
    title = (asset.display_title or asset.title or "Unbenannt").strip() or "Unbenannt"
    base = title
    for marker in PROJECT_TITLE_MARKERS:
        base = base.replace(marker, "")
    return base.strip() or title


def _existing_project_for_asset(db: Session, asset: AudioAsset) -> AudioProject | None:
    # Projekt-Identität darf nicht über Titel ermittelt werden. Titel können gleich
    # heißen oder nachträglich geändert werden. Sicher sind nur vorhandene IDs im
    # gleichen Song-/Task-/Audio-Kontext.
    candidate_project_ids: list[int] = []

    if asset.song_id is not None:
        song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if song and song.project_id:
            candidate_project_ids.append(int(song.project_id))
        candidate_project_ids.extend(
            int(row.project_id)
            for row in db.query(AudioAsset.project_id)
            .filter(AudioAsset.song_id == asset.song_id, AudioAsset.project_id.isnot(None), AudioAsset.is_deleted.is_(False))
            .all()
            if row.project_id is not None
        )

    if asset.suno_task_id:
        candidate_project_ids.extend(
            int(row.project_id)
            for row in db.query(AudioAsset.project_id)
            .filter(AudioAsset.suno_task_id == asset.suno_task_id, AudioAsset.project_id.isnot(None), AudioAsset.is_deleted.is_(False))
            .all()
            if row.project_id is not None
        )

    if asset.task_local_id is not None:
        candidate_project_ids.extend(
            int(row.project_id)
            for row in db.query(AudioAsset.project_id)
            .filter(AudioAsset.task_local_id == asset.task_local_id, AudioAsset.project_id.isnot(None), AudioAsset.is_deleted.is_(False))
            .all()
            if row.project_id is not None
        )

    for project_id in dict.fromkeys(candidate_project_ids):
        project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
        if project:
            return project
    return None


def auto_group_audio_projects(db: Session) -> int:
    updated = 0
    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all():
        if asset.project_id:
            continue

        project = _existing_project_for_asset(db, asset)
        if not project:
            project = AudioProject(title=_base_project_title(asset), cover_image_url=asset.image_url)
            db.add(project)
            db.flush()

        asset.project_id = project.id
        if asset.song_id:
            song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
            if song and not song.project_id:
                song.project_id = project.id
                db.add(song)
        if not project.cover_image_url and asset.image_url:
            project.cover_image_url = asset.image_url
        db.add(asset)
        updated += 1
    return updated


def _json_contains(value: Any, needle: str | None) -> bool:
    if not needle:
        return False
    try:
        text = json.dumps(value or {}, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value or "")
    return str(needle) in text


def _song_matches_asset(asset: AudioAsset, song: Song | None) -> bool:
    if not asset or not song:
        return False

    asset_audio_id = _norm(asset.audio_id)
    asset_source_url = _norm(asset.source_url)
    song_audio_url = _norm(song.audio_url)

    # WICHTIG: Eine Suno-Task-ID ist keine eindeutige Audio-Identität.
    # Ein Task kann mehrere Varianten erzeugen. Deshalb reichen nur harte
    # Audio-Beweise: Audio-ID, Audio-URL oder Metadaten mit exakt dieser Variante.
    if asset_source_url and song_audio_url and asset_source_url == song_audio_url:
        return True
    if asset_audio_id and song_audio_url and asset_audio_id in song_audio_url:
        return True
    if asset_audio_id and _json_contains(song.metadata_json, asset_audio_id):
        return True
    if asset_source_url and _json_contains(song.metadata_json, asset_source_url):
        return True
    return False


def _is_unambiguous_task_scope(db: Session, asset: AudioAsset, song: Song | None) -> bool:
    if not asset or not song:
        return False
    asset_task_id = _norm(asset.suno_task_id)
    song_task_id = _norm(song.task_id)
    if not asset_task_id or not song_task_id or asset_task_id != song_task_id:
        return False
    # Nur wenn es in diesem Task genau ein aktives AudioAsset und genau einen
    # aktiven Song gibt, darf die Task-ID als Fallback-Identität dienen.
    asset_count = db.query(AudioAsset).filter(
        AudioAsset.suno_task_id == asset_task_id,
        AudioAsset.is_deleted.is_(False),
    ).count()
    song_count = db.query(Song).filter(
        Song.task_id == song_task_id,
        Song.is_deleted.is_(False),
    ).count()
    return asset_count == 1 and song_count == 1


def _find_reliable_song_for_asset(db: Session, asset: AudioAsset) -> Song | None:
    candidates: list[Song] = []

    if asset.suno_task_id:
        candidates.extend(
            db.query(Song)
            .filter(Song.task_id == asset.suno_task_id, Song.is_deleted.is_(False))
            .order_by(Song.id.desc())
            .all()
        )

    if asset.source_url:
        candidates.extend(
            db.query(Song)
            .filter(Song.audio_url == asset.source_url, Song.is_deleted.is_(False))
            .order_by(Song.id.desc())
            .all()
        )

    if asset.task_local_id:
        task = db.query(SunoTask).filter(SunoTask.id == asset.task_local_id, SunoTask.is_deleted.is_(False)).first()
        if task and task.task_id:
            candidates.extend(
                db.query(Song)
                .filter(Song.task_id == task.task_id, Song.is_deleted.is_(False))
                .order_by(Song.id.desc())
                .all()
            )

    seen: set[int] = set()
    unique: list[Song] = []
    for song in candidates:
        if not song or not song.id or song.id in seen:
            continue
        seen.add(song.id)
        unique.append(song)

    for song in unique:
        if _song_matches_asset(asset, song):
            return song

    # Letzter, konservativer Fallback: Task-ID nur bei 1:1-Task-Scopes.
    for song in unique:
        if _is_unambiguous_task_scope(db, asset, song):
            return song
    return None


def repair_audio_asset_song_links(db: Session) -> int:
    """Repair only verifiable AudioAsset -> Song links.

    Alte Imports/Reparaturläufe konnten Assets über Titel oder globale Queue-Zustände
    optisch korrekt anzeigen, während `song_id`/`task_id` nicht mehr zum abgespielten
    Audio passten. Diese Reparatur ist bewusst konservativ: Links werden nur gesetzt,
    wenn Audio-ID oder Audio-URL eindeutig zusammenpassen. Task-ID wird nur bei
    echten 1:1-Scopes als Fallback akzeptiert. Nicht beweisbare
    Fehlverknüpfungen werden gelöst, damit Frontend und Player nicht fremde Songdetails
    mit einem anderen AudioAsset vermischen.
    """
    updated = 0
    rows = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all()
    for asset in rows:
        current_song = None
        if asset.song_id:
            current_song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()

        if current_song and (_song_matches_asset(asset, current_song) or _is_unambiguous_task_scope(db, asset, current_song)):
            continue

        reliable_song = _find_reliable_song_for_asset(db, asset)
        if reliable_song and asset.song_id != reliable_song.id:
            asset.song_id = reliable_song.id
            db.add(asset)
            updated += 1
            continue

        # Wenn ein vorhandener Link nachweislich nicht passt und kein sauberer Ersatz
        # gefunden wurde, wird er entfernt. Das ist sicherer als fremde Songdetails in
        # der Library mit einem anderen AudioAsset abzuspielen.
        if asset.song_id and current_song and not (_song_matches_asset(asset, current_song) or _is_unambiguous_task_scope(db, asset, current_song)):
            metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
            metadata.setdefault("link_repair", {})
            if isinstance(metadata["link_repair"], dict):
                metadata["link_repair"].update({
                    "previous_song_id": asset.song_id,
                    "previous_song_title": current_song.title,
                    "reason": "song_id did not match audio_asset task/audio/url identity",
                    "repaired_at": _now().isoformat(),
                })
            asset.song_id = None
            asset.metadata_json = metadata
            db.add(asset)
            updated += 1
    return updated


def repair_audio_library(db: Session) -> dict[str, Any]:
    invalid = quarantine_invalid_audio_assets(db)
    reconstructed = reconstruct_audio_assets_from_tasks(db)
    # Run quarantine again because reconstruction may have merged metadata onto old rows.
    invalid += quarantine_invalid_audio_assets(db)
    deduped = deduplicate_audio_assets(db)
    repaired_local = 0
    for asset in db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).all():
        if repair_local_file_metadata(asset):
            repaired_local += 1
            db.add(asset)
    fixed_extend = repair_extend_tasks_with_local_audio_ids(db)
    fixed_song_links = repair_audio_asset_song_links(db)
    grouped = auto_group_audio_projects(db)
    db.commit()
    return {
        "ok": True,
        "invalid_soft_deleted": invalid,
        "reconstructed_from_tasks": reconstructed,
        "duplicates_soft_deleted": deduped,
        "local_metadata_repaired": repaired_local,
        "extend_payloads_repaired": fixed_extend,
        "song_links_repaired": fixed_song_links,
        "projects_grouped": grouped,
        "active_audio_assets": db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).count(),
        "deleted_audio_assets": db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(True)).count(),
    }



def _task_title(task: SunoTask | None) -> str | None:
    if not task:
        return None
    for payload in (task.request_payload, task.response_payload, task.result_payload):
        if not isinstance(payload, dict):
            continue
        for key in ("title", "song_title", "name"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("title", "song_title", "name"):
                value = data.get(key)
                if value:
                    return str(value)
    return task.task_type or None


def _identity_key_for_asset(asset: AudioAsset) -> str:
    if asset.project_id is not None:
        return f"project-{asset.project_id}"
    if asset.song_id is not None:
        return f"song-{asset.song_id}"
    if asset.task_local_id is not None:
        return f"task-local-{asset.task_local_id}"
    if asset.suno_task_id:
        return f"suno-task-{asset.suno_task_id}"
    if asset.audio_id:
        return f"audio-id-{asset.audio_id}"
    return f"audio-{asset.id}"


def attach_audio_asset_identity_context(db: Session, rows: list[AudioAsset]) -> None:
    """Attach stable display/context attributes expected by AudioAssetRead.

    Titel sind nur Anzeige. Gruppierung, Routing und Player-Zuordnung müssen über
    stabile IDs laufen. Diese Attribute vermeiden, dass React Projekt-/Songtitel aus
    zufälligen Varianten ableitet.

    Generation-Options-Hinweis:
    Songdetails zeigen Suno-Request-Optionen wie negative_tags, vocal_gender,
    styleWeight, weirdnessConstraint und audioWeight aus `metadata_json`.
    Alt-/Importpfade haben diese Werte teils nur noch im verknüpften SunoTask.
    Deshalb wird der Task-Request hier read-only in die ausgelieferten Metadaten
    gespiegelt. Keine DB-Migration und kein Schreibzugriff daraus machen; der
    Listen-Endpunkt muss weiterhin leichtgewichtig bleiben.
    """
    if not rows:
        return

    project_ids = sorted({int(row.project_id) for row in rows if row.project_id is not None})
    song_ids = sorted({int(row.song_id) for row in rows if row.song_id is not None})
    task_local_ids = sorted({int(row.task_local_id) for row in rows if row.task_local_id is not None})

    projects = {
        project.id: project
        for project in db.query(AudioProject).filter(AudioProject.id.in_(project_ids)).all()
    } if project_ids else {}
    songs = {
        song.id: song
        for song in db.query(Song).filter(Song.id.in_(song_ids)).all()
    } if song_ids else {}
    tasks = {
        task.id: task
        for task in db.query(SunoTask).filter(SunoTask.id.in_(task_local_ids)).all()
    } if task_local_ids else {}

    for row in rows:
        project = projects.get(int(row.project_id)) if row.project_id is not None else None
        song = songs.get(int(row.song_id)) if row.song_id is not None else None
        task = tasks.get(int(row.task_local_id)) if row.task_local_id is not None else None

        project_title = project.title if project and not bool(getattr(project, "is_deleted", False)) else None
        song_title = song.title if song and not bool(getattr(song, "is_deleted", False)) else None
        task_title = _task_title(task)
        identity_key = _identity_key_for_asset(row)
        resolved_project_title = project_title or song_title or task_title or row.display_title or row.title or f"Audio {row.id}"
        resolved_display_title = row.display_title or row.title or song_title or project_title or task_title or f"Audio {row.id}"

        warning = None
        if row.song_id and not song:
            warning = "song_id points to missing/deleted song"
        elif row.project_id and not project:
            warning = "project_id points to missing/deleted project"

        setattr(row, "project_title", project_title)
        setattr(row, "song_title", song_title)
        setattr(row, "task_title", task_title)
        setattr(row, "resolved_project_title", resolved_project_title)
        setattr(row, "resolved_display_title", resolved_display_title)
        setattr(row, "identity_key", identity_key)
        setattr(row, "identity_warning", warning)

        if task and isinstance(task.request_payload, dict):
            metadata = dict(row.metadata_json or {}) if isinstance(row.metadata_json, dict) else {}
            existing_request = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
            merged_request = {**task.request_payload, **existing_request}
            metadata["request_payload"] = merged_request
            metadata.setdefault("task_request_payload", task.request_payload)
            set_committed_value(row, "metadata_json", metadata)

def _attach_task_created_at(db: Session, rows: list[AudioAsset]) -> None:
    task_ids = sorted({int(row.task_local_id) for row in rows if row.task_local_id is not None})
    task_created_by_id: dict[int, datetime] = {}
    if task_ids:
        task_created_by_id = {
            task.id: task.created_at
            for task in db.query(SunoTask).filter(SunoTask.id.in_(task_ids)).all()
            if task.created_at is not None
        }
    for row in rows:
        setattr(row, "task_created_at", task_created_by_id.get(int(row.task_local_id)) if row.task_local_id is not None else None)



def _asset_source_created_datetime(row: AudioAsset) -> datetime | None:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    for key in ("source_created_at", "created_at", "createdAt", "created", "createTime"):
        parsed = parse_source_datetime(metadata.get(key))
        if parsed:
            return parsed
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    for key in ("source_created_at", "created_at", "createdAt", "created", "createTime"):
        parsed = parse_source_datetime(candidate.get(key))
        if parsed:
            return parsed
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    for key in ("source_created_at", "created_at", "createdAt", "created", "createTime"):
        parsed = parse_source_datetime(request_payload.get(key))
        if parsed:
            return parsed
    return None

def _task_sort_datetime(row: AudioAsset) -> datetime:
    # Priorität: externes Suno/SunoAPI-Erstelldatum, dann Task-Datum, dann lokale Asset-Zeit.
    return _asset_source_created_datetime(row) or getattr(row, "task_created_at", None) or row.created_at or _now()




def _attach_transcript_flags(db: Session, rows: list[AudioAsset]) -> None:
    if not rows:
        return
    asset_ids = [int(row.id) for row in rows if row.id]
    if not asset_ids:
        return
    transcripts = (
        db.query(AudioTranscript)
        .filter(AudioTranscript.audio_asset_id.in_(asset_ids))
        .order_by(AudioTranscript.audio_asset_id.asc(), AudioTranscript.updated_at.desc(), AudioTranscript.id.desc())
        .all()
    )
    latest: dict[int, AudioTranscript] = {}
    for transcript in transcripts:
        asset_id = int(transcript.audio_asset_id or 0)
        if asset_id and asset_id not in latest:
            latest[asset_id] = transcript
    for row in rows:
        transcript = latest.get(int(row.id or 0))
        srt_cached = bool(transcript and transcript.status == "completed" and transcript.srt_text)
        half_cached = False
        if srt_cached and transcript and transcript.srt_path:
            try:
                srt_path = Path(str(transcript.srt_path)).expanduser().resolve()
                half_cached = srt_path.with_name(f"{srt_path.stem}.half.srt").exists()
            except Exception:
                half_cached = False
        setattr(row, "srt_cached", srt_cached)
        setattr(row, "half_srt_cached", half_cached)
        setattr(row, "latest_srt_status", transcript.status if transcript else None)
        setattr(row, "latest_srt_generated_at", transcript.generated_at if transcript else None)

def _attach_display_safe_waveform_segments(rows: list[AudioAsset]) -> None:
    """Normalize waveform segment labels for API output without DB writes.

    The Library may receive stale waveform_json from older generated songs. The
    database can be correct while an already loaded React asset still contains
    raw descriptor segments. This read-time presentation guard makes the API
    always prefer cleaned structure_segments_json and never emits tags like
    "bass-heavy" or "Verse: gritty male vocals" as waveform labels.
    """
    for row in rows:
        if not row.waveform_json:
            continue
        payload = sanitize_waveform_payload_for_asset(row, row.waveform_json)
        if not payload:
            continue
        row.waveform_json = payload
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if isinstance(segments, list) and segments:
            row.structure_segments_json = segments


def active_usable_audio_assets(db: Session, limit: int = 500) -> list[AudioAsset]:
    # WICHTIG: read-only. repair_audio_library() (Scan + Datei-I/O + commit) darf
    # NICHT im normalen Listen-/Read-Pfad laufen – das erzeugte bei jedem
    # Library-Poll einen SQLite-Schreiblock und damit App-Trägheit/Login-Hänger.
    # Reparaturen laufen jetzt beim Startup, per Admin-Endpoint und Watchdog.
    # Für die Library ist die echte Reihenfolge das externe Suno/SunoAPI-Datum,
    # nicht die lokale Insert-/Repair-Zeit. Deshalb laden wir bewusst etwas breiter
    # und sortieren danach im Python-Kontext über metadata_json.source_created_at,
    # candidate.createTime, Task-Datum und erst zuletzt lokale created_at.
    scan_limit = max(limit * 8, 2000)
    rows = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.created_at.desc(), AudioAsset.id.desc())
        .limit(scan_limit)
        .all()
    )
    _attach_task_created_at(db, rows)
    rows = [row for row in rows if not is_bad_image_asset(row) and (is_audio_url(row.source_url) or row.public_url or row.local_path)]
    for row in rows:
        source_dt = _asset_source_created_datetime(row)
        sort_dt = _task_sort_datetime(row)
        setattr(row, "source_created_at", source_dt.isoformat() if source_dt else None)
        setattr(row, "library_sort_at", sort_dt.isoformat() if sort_dt else None)
    rows.sort(key=lambda row: (_task_sort_datetime(row), _asset_score(row), row.id or 0), reverse=True)
    seen: set[str] = set()
    result: list[AudioAsset] = []
    for row in rows:
        key = row.audio_id or row.checksum_sha256 or row.source_url or f"id:{row.id}"
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    result.sort(key=lambda row: (_task_sort_datetime(row), row.id or 0), reverse=True)
    # Kontextfelder nach Dedupe nochmals setzen, damit Pydantic sie sicher ausliefert.
    for row in result:
        source_dt = _asset_source_created_datetime(row)
        sort_dt = _task_sort_datetime(row)
        setattr(row, "source_created_at", source_dt.isoformat() if source_dt else None)
        setattr(row, "library_sort_at", sort_dt.isoformat() if sort_dt else None)
    attach_audio_asset_identity_context(db, result)
    _attach_transcript_flags(db, result)
    _attach_display_safe_waveform_segments(result)
    return result
