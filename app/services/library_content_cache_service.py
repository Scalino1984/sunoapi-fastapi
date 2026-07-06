"""Library content cache and repair routines.

"Inhalte pruefen" ist der explizite Wartungspfad fuer lokale/offline Library-
Konsistenz. Normale Library-/Songdetails-Reads duerfen keine Live-SunoAPI-
Abfragen oder schwere Reparaturen ausloesen. Fehlende SunoAPI-Generate-
Optionen alter importierter Tasks werden hier gezielt ueber den MusicService-
Provider-Backfill nachgezogen und lokal in Task/Song/AudioAsset-Metadaten
gespeichert.

Wichtig fuer Replicate-Cover: lokale cover_cache-Daten muessen mit vorhandenen
Remote-/Replicate-Quellfeldern zusammengefuehrt werden, nicht ersetzt. Sonst
zaehlt jeder erneute Lauf dieselben Cover-Metadaten wieder als repariert.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.services.portable_path_service import public_url_for_file, to_portable_path
from app.models import ActivityLog, AudioAsset, AudioProject, Song, StatusNotification, SunoTask
from app.services.audio_asset_repair_service import AUDIO_URL_PREFERENCE, is_audio_url, repair_local_file_metadata
from app.services.audio_asset_materialization_service import AudioAssetMaterializationService
from app.services.audio_cache_service import AudioCacheService, AudioCandidate, CoverCacheService
from app.services.music_service import MusicService
from app.services.task_lifecycle_service import append_task_debug_event, append_task_step_log
from app.utils.time_utils import utc_now_naive

IMAGE_URL_KEYS = (
    "source_image_url",
    "sourceImageUrl",
    "image_url",
    "imageUrl",
    "cover_image_url",
    "coverImageUrl",
    "thumbnail_url",
    "thumbnailUrl",
    "cover_source_url",
    "cover_origin_url",
    "replicate_source_url",
    "replicate_output_url",
    "replicate_remote_url",
    "remote_url",
    "source_url",
)


def _metadata_dict(value: dict | None) -> dict:
    return value if isinstance(value, dict) else {}


def _local_path_inside_root(value: Any, root: Path, public_route: str) -> Path | None:
    if not value:
        return None
    raw = str(value).strip().split("?", 1)[0]
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return None
    path_text = unquote(parsed.path if parsed.scheme else raw)
    normalized = path_text.replace("\\", "/")
    candidates: list[Path] = []
    direct = Path(path_text)
    candidates.append(direct)
    if direct.name:
        candidates.append(root / direct.name)
    route = public_route.rstrip("/")
    if route and normalized.startswith(route + "/"):
        rel = normalized[len(route):].lstrip("/")
        if rel and ".." not in Path(rel).parts:
            candidates.append(root / rel)
    marker = "/storage/audio/"
    if marker in normalized:
        rel = normalized.rsplit(marker, 1)[-1].lstrip("/")
        if rel and ".." not in Path(rel).parts:
            candidates.append(root / rel)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).expanduser().resolve()
            resolved.relative_to(root)
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _audio_local_path(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    root = settings.audio_storage_path.expanduser().resolve()
    for value in (asset.local_path, asset.filename, asset.public_url):
        path = _local_path_inside_root(value, root, settings.suno_audio_public_route)
        if path:
            return path
    return None


def ensure_audio_asset_local_metadata(asset: AudioAsset) -> tuple[bool, bool]:
    """Prüft lokale Audio-Dateien im aktuellen Audio-Storage und repariert nur echte Abweichungen.

    Wichtig: Diese Funktion muss idempotent bleiben. Sie darf einen bereits
    korrekt gespeicherten Datensatz nicht bei jedem Prüflauf erneut als
    "Metadaten repariert" zählen. Deshalb wird hier bewusst kein breiter
    Repair-Helper mit zusätzlicher Dauer-/MIME-Erkennung aufgerufen, sondern
    nur der portable Kernzustand verglichen.

    Rückgabe: `(exists, changed)`.
    """
    path = _audio_local_path(asset)
    if not path:
        return False, False
    settings = get_settings()
    changed = False
    updates = {
        "status": "cached",
        "local_path": to_portable_path(path, storage_root=settings.audio_storage_path),
        "filename": path.name,
        "public_url": public_url_for_file(path, storage_root=settings.audio_storage_path, public_route=settings.suno_audio_public_route),
        "file_size_bytes": path.stat().st_size,
    }
    for key, value in updates.items():
        if getattr(asset, key) != value:
            setattr(asset, key, value)
            changed = True
    if asset.error_message:
        asset.error_message = None
        changed = True
    return True, changed



def _walk_payload_values(value: Any, *, max_items: int = 5000) -> list[Any]:
    """Liefert verschachtelte Payload-Werte begrenzt zurück.

    Viele Schnittstellen legen URLs tief in response_payload/result_payload,
    metadata_json oder candidate-Strukturen ab. Diese Funktion ist rein
    read-only und bewusst begrenzt, damit "Inhalte prüfen" keine extremen
    Payloads rekursiv auswalzt.
    """
    values: list[Any] = []
    stack: list[Any] = [value]
    seen = 0
    while stack and seen < max_items:
        item = stack.pop()
        seen += 1
        if isinstance(item, dict):
            values.extend(item.values())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple, set)):
            values.extend(item)
            stack.extend(item)
        else:
            values.append(item)
    return values


def _add_unique_url(target: list[str], seen: set[str], value: Any, *, media_type: str) -> None:
    if not isinstance(value, str):
        return
    text = value.strip()
    if not text or text in seen:
        return
    if media_type == "audio":
        if not is_audio_url(text):
            return
    elif media_type == "image":
        if not _is_external_cover_url(text):
            return
    else:
        return
    seen.add(text)
    target.append(text)


def _configured_remote_media_base_urls() -> list[str]:
    raw = str(get_settings().library_content_remote_media_base_urls or "").strip()
    if not raw:
        return []
    bases: list[str] = []
    seen: set[str] = set()
    for item in raw.replace("\n", ",").split(","):
        base = item.strip().rstrip("/")
        if not base or base in seen:
            continue
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(base)
        bases.append(base)
    return bases


def _media_route_reference(value: Any, route: str) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().split("?", 1)[0]
    if not text:
        return None
    route = route.rstrip("/")
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme else text
    normalized = unquote(path).replace("\\", "/")
    marker = route + "/"
    if normalized.startswith(marker):
        return normalized
    if marker in normalized:
        return marker + normalized.rsplit(marker, 1)[-1].lstrip("/")
    return None


def _remote_media_candidate_urls(value: Any, *, route: str) -> list[str]:
    media_ref = _media_route_reference(value, route)
    if not media_ref:
        return []
    return [f"{base}{media_ref}" for base in _configured_remote_media_base_urls()]


def _add_cover_url_candidates(target: list[str], seen: set[str], value: Any) -> None:
    _add_unique_url(target, seen, value, media_type="image")
    for remote_url in _remote_media_candidate_urls(value, route=get_settings().suno_cover_public_route):
        _add_unique_url(target, seen, remote_url, media_type="image")



def _is_cache_source_unavailable_error(message: str | None) -> bool:
    """Klassifiziert erwartbare Remote-Cache-Probleme.

    Externe Suno/CDN/Replicate-URLs können ablaufen, nicht direkt downloadbar
    sein oder Content-Types liefern, die bewusst nicht gespeichert werden. Das
    ist für "Inhalte prüfen" kein App-Fehler, solange die Library weiterhin über
    Remote-URL/Metadaten funktioniert.
    """
    text = str(message or "").lower()
    if not text:
        return False
    expected_markers = (
        "401", "403", "404", "410", "429",
        "forbidden", "unauthorized", "not found", "gone", "too many requests",
        "nicht erlaubter audio-typ", "nicht erlaubter cover-typ",
        "bild-url wird nicht als audio verarbeitet",
        "nur öffentliche http/https-urls sind erlaubt",
        "hostname kann nicht aufgelöst werden",
        "private oder lokale zieladresse ist nicht erlaubt",
        "download hat keine daten geliefert",
        "cover-download hat keine daten geliefert",
        "timed out", "timeout", "readtimeout", "connecttimeout",
    )
    return any(marker in text for marker in expected_markers)

def _related_task_payloads(db: Session, asset: AudioAsset, song: Song | None = None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    tasks: list[SunoTask] = []
    seen_task_ids: set[int] = set()

    def add_task(task: SunoTask | None) -> None:
        if not task or not getattr(task, "id", None) or int(task.id) in seen_task_ids:
            return
        seen_task_ids.add(int(task.id))
        tasks.append(task)

    if asset.task_local_id:
        add_task(db.query(SunoTask).filter(SunoTask.id == asset.task_local_id).first())
    if asset.suno_task_id:
        add_task(db.query(SunoTask).filter(SunoTask.task_id == asset.suno_task_id).order_by(SunoTask.id.desc()).first())
    if song and song.task_id:
        add_task(db.query(SunoTask).filter(SunoTask.task_id == song.task_id).order_by(SunoTask.id.desc()).first())

    # Kleine Zusatzsuche für importierte Varianten: audio_id kommt oft nur im JSON vor.
    # SQLite JSON-Vollsuche wäre teuer; LIKE auf kleinen lokalen Datenbeständen ist hier
    # nur Fallback und auf wenige Treffer begrenzt.
    if asset.audio_id and len(str(asset.audio_id)) >= 8:
        needle = str(asset.audio_id)
        for task in (
            db.query(SunoTask)
            .filter(SunoTask.is_deleted.is_(False))
            .filter(
                (cast(SunoTask.request_payload, String).contains(needle))
                | (cast(SunoTask.response_payload, String).contains(needle))
                | (cast(SunoTask.result_payload, String).contains(needle))
            )
            .order_by(SunoTask.updated_at.desc())
            .limit(5)
            .all()
        ):
            add_task(task)

    for task in tasks:
        for payload in (task.request_payload, task.response_payload, task.result_payload):
            if isinstance(payload, dict):
                payloads.append(payload)
    return payloads


def _context_payloads_for_asset(db: Session, asset: AudioAsset, song: Song | None = None, project: AudioProject | None = None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for payload in (asset.metadata_json, song.metadata_json if song else None, project.metadata_json if project else None):
        if isinstance(payload, dict):
            payloads.append(payload)
    payloads.extend(_related_task_payloads(db, asset, song=song))
    return payloads

def _known_audio_urls(db: Session, asset: AudioAsset, song: Song | None = None, project: AudioProject | None = None) -> list[str]:
    """Sammelt echte Audio-URLs aus allen bekannten Schnittstellen-Kontexten.

    Quellen: AudioAsset-Felder, AudioAsset-Metadaten, Song/Projekt-Metadaten
    sowie zugehörige SunoTask request/response/result Payloads. Suno-Share-
    Seiten werden durch is_audio_url bewusst ausgeschlossen.
    """
    metadata = _metadata_dict(asset.metadata_json)
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    urls: list[str] = []
    seen: set[str] = set()

    preferred_order = (
        "audioUrl",
        "audio_url",
        "downloadUrl",
        "download_url",
        "mp3Url",
        "mp3_url",
        "wavUrl",
        "wav_url",
        "sourceAudioUrl",
        "source_audio_url",
        "streamAudioUrl",
        "stream_audio_url",
        "sourceStreamAudioUrl",
        "source_stream_audio_url",
        "url",
    )
    direct_sources = [candidate, metadata, request_payload]
    if song:
        direct_sources.append({
            "audio_url": song.audio_url,
            "wav_url": song.wav_url,
            "midi_url": song.midi_url,
        })
    direct_sources.append({
        "source_audio_url": asset.source_audio_url,
        "stream_audio_url": asset.stream_audio_url,
        "source_url": asset.source_url,
        "public_url": asset.public_url,
    })

    for source in direct_sources:
        if not isinstance(source, dict):
            continue
        for key in preferred_order:
            _add_unique_url(urls, seen, source.get(key), media_type="audio")
    for source in (*direct_sources, *_context_payloads_for_asset(db, asset, song=song, project=project)):
        if not isinstance(source, dict):
            continue
        for key in AUDIO_URL_PREFERENCE:
            _add_unique_url(urls, seen, source.get(key), media_type="audio")
        for value in _walk_payload_values(source):
            _add_unique_url(urls, seen, value, media_type="audio")
    return urls


def _known_cover_urls(db: Session, asset: AudioAsset, song: Song | None = None, project: AudioProject | None = None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for value in (asset.image_url, song.cover_image_url if song else None, project.cover_image_url if project else None):
        _add_cover_url_candidates(urls, seen, value)
    for payload in _context_payloads_for_asset(db, asset, song=song, project=project):
        direct = _metadata_source_url(payload, *IMAGE_URL_KEYS)
        _add_cover_url_candidates(urls, seen, direct)
        for value in _walk_payload_values(payload):
            if isinstance(value, str):
                lowered = value.lower().split("?", 1)[0]
                if lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")) or _media_route_reference(value, get_settings().suno_cover_public_route):
                    _add_cover_url_candidates(urls, seen, value)
    return urls

def _is_external_cover_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _metadata_source_url(metadata: dict | None, *keys: str) -> str | None:
    meta = _metadata_dict(metadata)
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    cover_cache = meta.get("cover_cache") if isinstance(meta.get("cover_cache"), dict) else {}
    generated_cover = meta.get("generated_cover") if isinstance(meta.get("generated_cover"), dict) else {}
    candidate = meta.get("candidate") if isinstance(meta.get("candidate"), dict) else {}
    for source in (cover_cache, generated_cover, candidate):
        for key in (*IMAGE_URL_KEYS, "replicate_source_url", "source_url", "remote_url"):
            value = source.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def _first_external_cover_source(*payloads: Any) -> str | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        direct = _metadata_source_url(payload, *IMAGE_URL_KEYS)
        if direct and _is_external_cover_url(direct):
            return direct
        for nested_key in ("cover_cache", "generated_cover", "result_payload", "response_payload", "candidate", "metadata"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                nested_source = _metadata_source_url(nested, *IMAGE_URL_KEYS)
                if nested_source and _is_external_cover_url(nested_source):
                    return nested_source
    return None


def _merge_generated_cover_source(metadata: dict | None, source_url: str, task_payload: dict | None = None) -> tuple[dict, bool]:
    merged = dict(metadata or {})
    changed = False

    def set_missing(container: dict, key: str, value: Any) -> None:
        nonlocal changed
        if value is None or value == "":
            return
        if container.get(key) != value and not container.get(key):
            container[key] = value
            changed = True

    aliases = {
        "source_image_url": source_url,
        "cover_source_url": source_url,
        "cover_origin_url": source_url,
        "replicate_source_url": source_url,
        "replicate_output_url": source_url,
        "remote_url": source_url,
    }
    for key, value in aliases.items():
        set_missing(merged, key, value)

    cover_cache = dict(merged.get("cover_cache") or {}) if isinstance(merged.get("cover_cache"), dict) else {}
    for key, value in aliases.items():
        set_missing(cover_cache, key, value)
    set_missing(cover_cache, "status", "remote")
    set_missing(cover_cache, "backend", "replicate")
    set_missing(cover_cache, "source_url", source_url)
    if cover_cache and merged.get("cover_cache") != cover_cache:
        merged["cover_cache"] = cover_cache
        changed = True

    generated_cover = dict(merged.get("generated_cover") or {}) if isinstance(merged.get("generated_cover"), dict) else {}
    if isinstance(task_payload, dict):
        for key in ("model", "title", "cover_title", "genre", "note", "title_text_enabled"):
            if task_payload.get(key) is not None:
                set_missing(generated_cover, key, task_payload.get(key))
    for key, value in aliases.items():
        set_missing(generated_cover, key, value)
    set_missing(generated_cover, "backend", "replicate")
    set_missing(generated_cover, "source_url", source_url)
    if generated_cover and merged.get("generated_cover") != generated_cover:
        merged["generated_cover"] = generated_cover
        changed = True
    return merged, changed


def _hydrate_generated_cover_sources_from_tasks(db: Session, *, limit: int) -> int:
    fixed = 0
    tasks = (
        db.query(SunoTask)
        .filter(SunoTask.task_type == "generate_cover_art")
        .order_by(SunoTask.updated_at.desc())
        .limit(max(50, min(1000, int(limit or 500) * 2)))
        .all()
    )
    for task in tasks:
        result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        source_url = _first_external_cover_source(result_payload, request_payload)
        local_cover_ref = _first_local_cover_reference(result_payload, request_payload)
        if not source_url:
            source_url = None
        if not source_url and not local_cover_ref:
            continue
        audio_asset_id = result_payload.get("audio_asset_id") or request_payload.get("audio_asset_id")
        song_id = result_payload.get("song_id") or request_payload.get("song_id")
        asset = None
        song = None
        if audio_asset_id:
            try:
                asset = db.query(AudioAsset).filter(AudioAsset.id == int(audio_asset_id), AudioAsset.is_deleted.is_(False)).first()
            except Exception:
                asset = None
        if asset and asset.song_id:
            song_id = song_id or asset.song_id
        if song_id:
            try:
                song = db.query(Song).filter(Song.id == int(song_id), Song.is_deleted.is_(False)).first()
            except Exception:
                song = None
        if local_cover_ref:
            if asset and _apply_local_generated_cover_reference(asset, "image_url", local_cover_ref, result_payload, source_url=source_url):
                db.add(asset)
                flag_modified(asset, "metadata_json")
                fixed += 1
            if song and _apply_local_generated_cover_reference(song, "cover_image_url", local_cover_ref, result_payload, source_url=source_url):
                db.add(song)
                flag_modified(song, "metadata_json")
                fixed += 1
            project_id = asset.project_id if asset and asset.project_id else (song.project_id if song and song.project_id else None)
            if project_id:
                project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
                if project and _apply_local_generated_cover_reference(project, "cover_image_url", local_cover_ref, result_payload, source_url=source_url):
                    db.add(project)
                    flag_modified(project, "metadata_json")
                    fixed += 1
        if source_url:
            if asset:
                meta, changed = _merge_generated_cover_source(asset.metadata_json if isinstance(asset.metadata_json, dict) else {}, source_url, result_payload)
                if changed:
                    asset.metadata_json = meta
                    db.add(asset)
                    flag_modified(asset, "metadata_json")
                    fixed += 1
            if song:
                meta, changed = _merge_generated_cover_source(song.metadata_json if isinstance(song.metadata_json, dict) else {}, source_url, result_payload)
                if changed:
                    song.metadata_json = meta
                    db.add(song)
                    flag_modified(song, "metadata_json")
                    fixed += 1
            project_id = asset.project_id if asset and asset.project_id else (song.project_id if song and song.project_id else None)
            if project_id:
                project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
                if project:
                    meta, changed = _merge_generated_cover_source(project.metadata_json if isinstance(project.metadata_json, dict) else {}, source_url, result_payload)
                    if changed:
                        project.metadata_json = meta
                        db.add(project)
                        flag_modified(project, "metadata_json")
                        fixed += 1
    if fixed:
        db.flush()
    return fixed


def _local_cover_exists(value: str | None) -> bool:
    return _local_cover_path(value) is not None


def _local_cover_path(value: str | None) -> Path | None:
    if not value:
        return None
    settings = get_settings()
    root = settings.cover_storage_path.expanduser().resolve()
    route = settings.suno_cover_public_route.rstrip("/")
    text = str(value).split("?", 1)[0]
    candidates: list[Path] = []
    if route and text.startswith(route + "/"):
        rel = text[len(route):].lstrip("/")
        if rel and ".." not in Path(rel).parts:
            candidates.append(root / rel)
    candidate = Path(text)
    candidates.append(candidate)
    if candidate.name:
        candidates.append(root / candidate.name)
    for path in candidates:
        try:
            resolved = path.expanduser().resolve() if path.is_absolute() else (root / path).expanduser().resolve()
            resolved.relative_to(root)
        except Exception:
            continue
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _cover_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".avif": "image/avif",
    }.get(suffix, "image/jpeg")


def _cover_cache_metadata_for_local_path(path: Path, *, public_url: str | None = None, source_url: str | None = None, backend: str | None = None, status: str = "cached") -> dict[str, Any]:
    settings = get_settings()
    resolved = path.expanduser().resolve()
    data = resolved.read_bytes()
    public = public_url or public_url_for_file(resolved, storage_root=settings.cover_storage_path, public_route=settings.suno_cover_public_route)
    metadata = {
        "status": status,
        "source_url": source_url or public,
        "public_url": public,
        "local_path": to_portable_path(resolved, storage_root=settings.cover_storage_path),
        "filename": resolved.name,
        "checksum_sha256": hashlib.sha256(data).hexdigest(),
        "content_type": _cover_content_type(resolved),
        "file_size_bytes": len(data),
        "cached_at": utc_now_naive().isoformat(),
    }
    if backend:
        metadata["backend"] = backend
    return metadata


def _first_local_cover_reference(*payloads: Any) -> str | None:
    preferred_keys = (
        "cover_url",
        "coverUrl",
        "public_url",
        "publicUrl",
        "cover_image_url",
        "coverImageUrl",
        "image_url",
        "imageUrl",
        "local_path",
        "filename",
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str) and _local_cover_path(value):
                return value
        for nested_key in ("cover_cache", "generated_cover", "result_payload", "response_payload", "candidate", "metadata"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                nested_value = _first_local_cover_reference(nested)
                if nested_value:
                    return nested_value
        for value in _walk_payload_values(payload):
            if isinstance(value, str) and _local_cover_path(value):
                return value
    return None


def _merge_local_generated_cover_metadata(metadata: dict | None, cover_cache: dict[str, Any], task_payload: dict | None = None, source_url: str | None = None) -> tuple[dict, bool]:
    merged = dict(metadata or {})
    changed = False
    public_url = cover_cache.get("public_url")
    source = source_url or cover_cache.get("source_url") or public_url

    if source and merged.get("source_image_url") != source:
        merged["source_image_url"] = source
        changed = True
    existing_cover_cache = merged.get("cover_cache") if isinstance(merged.get("cover_cache"), dict) else {}
    stable_cover_cache = dict(existing_cover_cache)
    stable_cover_cache.update(cover_cache)
    same_cached_file = all(
        existing_cover_cache.get(key) == stable_cover_cache.get(key)
        for key in ("public_url", "local_path", "filename", "checksum_sha256", "file_size_bytes")
    )
    if same_cached_file and existing_cover_cache.get("cached_at"):
        stable_cover_cache["cached_at"] = existing_cover_cache.get("cached_at")
    if merged.get("cover_cache") != stable_cover_cache:
        merged["cover_cache"] = stable_cover_cache
        changed = True

    generated_cover = dict(merged.get("generated_cover") or {}) if isinstance(merged.get("generated_cover"), dict) else {}
    before_generated = dict(generated_cover)
    generated_cover.setdefault("backend", cover_cache.get("backend") or "replicate")
    if public_url:
        generated_cover.setdefault("public_url", public_url)
    if source:
        generated_cover.setdefault("source_url", source)
    if isinstance(task_payload, dict):
        for key in ("model", "title", "cover_title", "genre", "note", "safety_retry"):
            if task_payload.get(key) is not None and generated_cover.get(key) is None:
                generated_cover[key] = task_payload.get(key)
        if task_payload.get("replicate_source_url") and generated_cover.get("replicate_source_url") is None:
            generated_cover["replicate_source_url"] = task_payload.get("replicate_source_url")
    if generated_cover != before_generated or merged.get("generated_cover") != generated_cover:
        merged["generated_cover"] = generated_cover
        changed = True
    return merged, changed


def _apply_local_generated_cover_reference(target: Any, url_attr: str, cover_ref: str, task_payload: dict | None = None, source_url: str | None = None) -> bool:
    path = _local_cover_path(cover_ref)
    if not path:
        return False
    settings = get_settings()
    public_url = cover_ref if str(cover_ref).startswith(settings.suno_cover_public_route.rstrip("/") + "/") else public_url_for_file(path, storage_root=settings.cover_storage_path, public_route=settings.suno_cover_public_route)
    cover_cache = _cover_cache_metadata_for_local_path(path, public_url=public_url, source_url=source_url or public_url, backend="replicate", status="generated")
    changed = False
    current_url = getattr(target, url_attr, None)
    if current_url != public_url:
        setattr(target, url_attr, public_url)
        changed = True
    meta, meta_changed = _merge_local_generated_cover_metadata(target.metadata_json if isinstance(target.metadata_json, dict) else {}, cover_cache, task_payload=task_payload, source_url=source_url or public_url)
    if meta_changed:
        target.metadata_json = meta
        changed = True
    return changed


def _repair_generation_options_from_tasks(db: Session, *, limit: int = 500) -> int:
    """Repair imported SunoAPI generation options for Library "Inhalte pruefen".

    The normal import path now normalizes negativeTags/vocalGender/slider values
    immediately. This repair path keeps older local databases consistent when
    users run the Library content check.
    """
    service = MusicService(db)
    changed_count = 0
    rows = (
        db.query(SunoTask)
        .filter(SunoTask.is_deleted.is_(False))
        .order_by(SunoTask.updated_at.desc(), SunoTask.id.desc())
        .limit(max(1, int(limit or 500)))
        .all()
    )
    for task in rows:
        try:
            if service._repair_imported_task_generation_options(task):
                changed_count += 1
        except Exception:
            continue
    if changed_count:
        db.flush()
    return changed_count


async def cache_missing_library_content_once(
    db: Session,
    *,
    limit: int = 500,
    notify_always: bool = True,
    background: bool = False,
) -> dict[str, Any]:
    audio_service = AudioCacheService(db)
    cover_service = CoverCacheService(db)
    audio_cached = 0
    cover_cached = 0
    skipped = 0
    failed = 0
    unavailable = 0
    stale_metadata_fixed = 0
    assets_checked = 0
    songs_checked = 0
    audio_attempted = 0
    cover_attempted = 0
    error_examples: list[dict[str, Any]] = []
    unavailable_examples: list[dict[str, Any]] = []

    def add_error(scope: str, item_id: int | None, message_text: str) -> None:
        if len(error_examples) >= 12:
            return
        error_examples.append({"scope": scope, "id": item_id, "error": str(message_text)[:500]})

    def add_unavailable(scope: str, item_id: int | None, message_text: str) -> None:
        if len(unavailable_examples) >= 12:
            return
        unavailable_examples.append({"scope": scope, "id": item_id, "reason": str(message_text)[:500]})

    materialized_from_tasks = AudioAssetMaterializationService(db).materialize_recent_tasks(limit=max(80, int(limit or 500)), force=True)
    materialization_changed = int(materialized_from_tasks.created or 0) + int(materialized_from_tasks.updated or 0)
    cover_metadata_fixed = _hydrate_generated_cover_sources_from_tasks(db, limit=limit)
    generation_options_repair_limit = min(1000, max(80, int(limit or 500)))
    generation_options_fixed = _repair_generation_options_from_tasks(db, limit=generation_options_repair_limit)
    generation_options_fixed += await MusicService(db).repair_imported_task_generation_options_from_provider(limit=generation_options_repair_limit)
    stale_metadata_fixed += cover_metadata_fixed
    stale_metadata_fixed += generation_options_fixed

    assets = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.updated_at.desc())
        .limit(limit)
        .all()
    )

    for asset in assets:
        assets_checked += 1
        try:
            audio_exists, metadata_changed = ensure_audio_asset_local_metadata(asset)
            if audio_exists:
                if metadata_changed:
                    db.add(asset)
                    stale_metadata_fixed += 1
            else:
                cached = False
                errors: list[str] = []
                song = db.query(Song).filter(Song.id == asset.song_id).first() if asset.song_id else None
                project = db.query(AudioProject).filter(AudioProject.id == asset.project_id).first() if asset.project_id else None
                audio_sources = _known_audio_urls(db, asset, song=song, project=project)
                for source_url in audio_sources:
                    candidate_meta = _metadata_dict(asset.metadata_json).get("candidate")
                    candidate = AudioCandidate(
                        source_url=source_url,
                        audio_id=asset.audio_id,
                        title=asset.display_title or asset.title,
                        image_url=asset.image_url,
                        duration_seconds=asset.duration_seconds,
                        metadata=candidate_meta if isinstance(candidate_meta, dict) else _metadata_dict(asset.metadata_json),
                    )
                    audio_attempted += 1
                    try:
                        result = await audio_service.cache_asset_from_candidate(asset, candidate, task=None, song=song)
                    except Exception as exc:
                        errors.append(str(exc))
                        continue
                    if result and result.status == "cached":
                        audio_cached += 1
                        cached = True
                        break
                if not cached:
                    if errors:
                        asset.status = "remote" if audio_sources else "missing"
                        asset.error_message = errors[-1]
                        db.add(asset)
                        if all(_is_cache_source_unavailable_error(item) for item in errors):
                            unavailable += 1
                            add_unavailable("audio_asset_audio", asset.id, errors[-1])
                        else:
                            failed += 1
                            add_error("audio_asset_audio", asset.id, errors[-1])
                    else:
                        skipped += 1

            if not _local_cover_exists(asset.cover_local_url or asset.image_url):
                song_for_cover = db.query(Song).filter(Song.id == asset.song_id).first() if asset.song_id else None
                project_for_cover = db.query(AudioProject).filter(AudioProject.id == asset.project_id).first() if asset.project_id else None
                cover_errors: list[str] = []
                for cover_source in _known_cover_urls(db, asset, song=song_for_cover, project=project_for_cover):
                    cover_attempted += 1
                    try:
                        result = await cover_service.cache_asset_cover(asset, image_url=cover_source)
                    except Exception as exc:
                        cover_errors.append(str(exc))
                        continue
                    if result:
                        cover_cached += 1
                        break
                if cover_errors and not _local_cover_exists(asset.cover_local_url or asset.image_url):
                    if all(_is_cache_source_unavailable_error(item) for item in cover_errors):
                        unavailable += 1
                        add_unavailable("audio_asset_cover", asset.id, cover_errors[-1])
                    else:
                        failed += 1
                        add_error("audio_asset_cover", asset.id, cover_errors[-1])
        except Exception as exc:
            failed += 1
            add_error("audio_asset", getattr(asset, "id", None), str(exc))

    songs = (
        db.query(Song)
        .filter(Song.is_deleted.is_(False))
        .order_by(Song.updated_at.desc())
        .limit(limit)
        .all()
    )
    for song in songs:
        songs_checked += 1
        try:
            if _local_cover_exists(song.cover_local_url or song.cover_image_url):
                continue
            cover_sources: list[str] = []
            cover_seen: set[str] = set()
            direct_source = song.cover_image_url if _is_external_cover_url(song.cover_image_url) else _metadata_source_url(song.metadata_json, "source_image_url", "cover_image_url")
            _add_cover_url_candidates(cover_sources, cover_seen, direct_source)
            _add_cover_url_candidates(cover_sources, cover_seen, song.cover_image_url)
            if not cover_sources:
                continue
            song_cover_errors: list[str] = []
            for cover_source in cover_sources:
                cover_attempted += 1
                try:
                    result = await cover_service.cache_song_cover(song, image_url=cover_source)
                except Exception as exc:
                    song_cover_errors.append(str(exc))
                    continue
                if result:
                    cover_cached += 1
                    break
            if song_cover_errors and not _local_cover_exists(song.cover_local_url or song.cover_image_url):
                raise ValueError(song_cover_errors[-1])
        except Exception as exc:
            if _is_cache_source_unavailable_error(str(exc)):
                unavailable += 1
                add_unavailable("song_cover", getattr(song, "id", None), str(exc))
            else:
                failed += 1
                add_error("song_cover", getattr(song, "id", None), str(exc))

    changed_total = audio_cached + cover_cached + stale_metadata_fixed + materialization_changed
    materialization_note = f" Materialisierung geändert: {materialization_changed}." if materialization_changed else ""
    message = f"Inhalte geprüft: {audio_cached} Audios, {cover_cached} Cover nachgeladen. Metadaten repariert: {stale_metadata_fixed}.{materialization_note} Übersprungen: {skipped}, nicht cachebar: {unavailable}, Fehler: {failed}."
    result_payload = {
        "audio_cached": audio_cached,
        "cover_cached": cover_cached,
        "stale_metadata_fixed": stale_metadata_fixed,
        "materialized_assets_created": int(materialized_from_tasks.created or 0),
        "materialized_assets_updated": int(materialized_from_tasks.updated or 0),
        "materialization_changed": materialization_changed,
        "cover_metadata_fixed": cover_metadata_fixed,
        "generation_options_fixed": generation_options_fixed,
        "assets_checked": assets_checked,
        "songs_checked": songs_checked,
        "audio_attempted": audio_attempted,
        "cover_attempted": cover_attempted,
        "skipped": skipped,
        "unavailable": unavailable,
        "failed": failed,
        "unavailable_examples": unavailable_examples,
        "error_examples": error_examples,
        "background": background,
        "limit": limit,
    }
    local_task = SunoTask(
        task_id=f"local-library-content-cache-{utc_now_naive().strftime('%Y%m%d%H%M%S%f')}",
        task_type="library_content_cache",
        status="SUCCESS" if failed == 0 else "PARTIAL_SUCCESS",
        request_payload={"limit": limit, "background": background},
        response_payload={},
        result_payload=result_payload,
        started_at=utc_now_naive(),
        completed_at=utc_now_naive(),
    )
    db.add(local_task)
    db.flush()
    append_task_debug_event(
        db,
        local_task,
        event="library_content_cache_finished",
        detail=message,
        level="info" if failed == 0 else "warning",
        data=result_payload,
        commit=False,
    )
    append_task_step_log(
        db,
        local_task,
        phase="completed" if failed == 0 else "partial_success",
        phase_label="Library-Inhalte geprüft",
        detail=message,
        data={
            "audio_cached": audio_cached,
            "cover_cached": cover_cached,
            "stale_metadata_fixed": stale_metadata_fixed,
            "materialization_changed": materialization_changed,
            "failed": failed,
            "unavailable": unavailable,
        },
        commit=False,
    )

    db.add(ActivityLog(
        action="background_cache_missing_library_content" if background else "cache_missing_library_content",
        content_type="system",
        content_id=None,
        new_value=result_payload,
        metadata_json={"limit": limit},
    ))

    should_notify = notify_always or (background and changed_total > 0)
    if should_notify:
        if background and changed_total > 0:
            title = "Neue Inhalte wurden geladen"
            notification_message = f"Neue Inhalte wurden geladen: {audio_cached} Audios, {cover_cached} Cover, {stale_metadata_fixed} Metadaten repariert{f', {materialization_changed} Materialisierung geändert' if materialization_changed else ''}."
            event_type = "library_content_background_loaded"
        else:
            title = "Library-Inhalte geprüft"
            notification_message = f"Nachgeladen: {audio_cached} Audios, {cover_cached} Cover. Metadaten repariert: {stale_metadata_fixed}.{materialization_note} Übersprungen: {skipped}, nicht cachebar: {unavailable}, Fehler: {failed}."
            event_type = "library_content_cache_completed"
        db.add(StatusNotification(
            event_type=event_type,
            title=title,
            message=notification_message,
            severity="success" if failed == 0 else "warning",
            status="unread",
            task_local_id=local_task.id,
            suno_task_id=local_task.task_id,
            content_type="system",
            content_id=local_task.id,
            target_tab="library",
            target_payload=result_payload,
            completed_at=utc_now_naive(),
        ))
    db.commit()

    return {
        "ok": True,
        "audio_cached": audio_cached,
        "cover_cached": cover_cached,
        "stale_metadata_fixed": stale_metadata_fixed,
        "materialized_assets_created": int(materialized_from_tasks.created or 0),
        "materialized_assets_updated": int(materialized_from_tasks.updated or 0),
        "materialization_changed": materialization_changed,
        "cover_metadata_fixed": cover_metadata_fixed,
        "generation_options_fixed": generation_options_fixed,
        "assets_checked": assets_checked,
        "songs_checked": songs_checked,
        "audio_attempted": audio_attempted,
        "cover_attempted": cover_attempted,
        "skipped": skipped,
        "unavailable": unavailable,
        "failed": failed,
        "unavailable_examples": unavailable_examples,
        "error_examples": error_examples,
        "background": background,
        "message": message,
    }
