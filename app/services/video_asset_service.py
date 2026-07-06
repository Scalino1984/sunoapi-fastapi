from __future__ import annotations

# CORE CONTRACT
# Zweck: Lokale Persistenz fuer SunoAPI-MP4-Videos.
# Kritische Logik: Videos bleiben eigene video_assets und duerfen niemals als
# audio_assets materialisiert werden. Audio, SRT, Stems und Waveform haengen
# weiterhin ausschliesslich an AudioAsset-IDs.
# Root-Fix: SunoAPI-MP4-Links sind nur zeitlich begrenzt verfuegbar; erfolgreiche
# create_video Tasks werden deshalb beim Polling/Callback sofort lokal gesichert.

import hashlib
import json
import ipaddress
import mimetypes
import socket
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.config import get_settings
from app.models import AudioAsset, Song, SunoTask, VideoAsset
from app.services.portable_path_service import public_url_for_file, resolve_portable_path, to_portable_path
from app.utils.time_utils import utc_now_naive

VIDEO_URL_KEYS = {
    "video_url",
    "videourl",
    "mp4_url",
    "mp4url",
    "download_url",
    "downloadurl",
    "url",
}
VIDEO_SUCCESS_FLAGS = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE"}
VIDEO_FAILED_FLAGS = {"FAILED", "ERROR", "CREATE_TASK_FAILED", "GENERATE_MP4_FAILED", "CALLBACK_EXCEPTION"}


def _walk(value: Any):
    # SunoAPI.org record-info speichert die urspruenglichen Request-Parameter je
    # nach Endpoint als JSON-String in data.param. Fuer importierte MP4-Tasks muss
    # audioId/musicId dort ebenfalls gefunden werden, sonst kann kein video_assets
    # Eintrag an das vorhandene AudioAsset gebunden werden.
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, str):
        text = value.strip()
        if text and text[0] in "[{" and len(text) <= 500_000:
            try:
                parsed = json.loads(text)
            except Exception:
                return
            if isinstance(parsed, (dict, list)):
                yield from _walk(parsed)


def _normalize_key(key: str) -> str:
    return key.replace("-", "_").replace(" ", "_").lower()


def _first_str(payload: Any, keys: Iterable[str]) -> str | None:
    key_set = {_normalize_key(key) for key in keys}
    for item in _walk(payload):
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if _normalize_key(str(key)) in key_set and value not in (None, ""):
                return str(value)
    return None


def extract_video_status(payload: Any) -> str | None:
    """SunoAPI MP4 nutzt data.successFlag; msg='success' ist nur HTTP-Envelope.

    Diese Funktion ist absichtlich strikt, damit PENDING-Videos nicht mehr als
    abgeschlossen markiert werden und das Polling nicht vor videoUrl endet.
    """
    for item in _walk(payload):
        if isinstance(item, dict):
            value = item.get("successFlag") or item.get("success_flag")
            if value:
                return str(value).strip().upper()
    for item in _walk(payload):
        if isinstance(item, dict):
            value = item.get("status") or item.get("state")
            if value:
                return str(value).strip().upper()
    return None


def is_video_success_status(status: str | None) -> bool:
    return str(status or "").strip().upper() in VIDEO_SUCCESS_FLAGS


def is_video_terminal_status(status: str | None) -> bool:
    normalized = str(status or "").strip().upper()
    return normalized in VIDEO_SUCCESS_FLAGS or normalized in VIDEO_FAILED_FLAGS


def extract_video_url(payload: Any) -> str | None:
    for item in _walk(payload):
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                continue
            normalized = _normalize_key(str(key))
            if normalized in VIDEO_URL_KEYS or _url_extension(value) in get_settings().video_allowed_extensions_list:
                return value
    return None


def _url_extension(value: str | None) -> str:
    if not value:
        return ""
    return Path(unquote(urlparse(str(value)).path)).suffix.lower()


def _safe_filename_stem(value: str | None, fallback: str) -> str:
    import re

    base = str(value or fallback).strip() or fallback
    base = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", base)
    base = re.sub(r"\s+", "_", base).strip(" ._- ")
    base = re.sub(r"_+", "_", base)
    return (base or fallback)[:100]


def _is_public_http_url(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "0.0.0.0"}:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


def _content_type_allowed(content_type: str | None) -> bool:
    if not content_type:
        return True
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized in get_settings().video_allowed_content_types_list or normalized.startswith("video/")


class VideoAssetService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def find_audio_asset_for_task(self, task: SunoTask) -> AudioAsset | None:
        request = task.request_payload if isinstance(task.request_payload, dict) else {}
        result = task.result_payload if isinstance(task.result_payload, dict) else {}
        response = task.response_payload if isinstance(task.response_payload, dict) else {}
        audio_id = _first_str([request, result, response], ("audioId", "audio_id", "musicId", "music_id"))
        parent_task_id = _first_str([request, result, response], ("taskId", "task_id", "sourceTaskId", "source_task_id"))

        query = self.db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False))
        if audio_id:
            asset = query.filter(AudioAsset.audio_id == audio_id).order_by(AudioAsset.id.desc()).first()
            if asset:
                return asset
        if parent_task_id:
            asset = query.filter(AudioAsset.suno_task_id == parent_task_id).order_by(AudioAsset.id.desc()).first()
            if asset:
                return asset
        song = self._song_for_task(task)
        if song:
            asset = query.filter(AudioAsset.song_id == song.id).order_by(AudioAsset.id.desc()).first()
            if asset:
                return asset
        return None

    def materialize_video_task(self, task: SunoTask, *, song: Song | None = None, cache: bool = True) -> VideoAsset | None:
        video_url = extract_video_url([task.result_payload, task.response_payload])
        if not video_url:
            return None
        asset = self.find_audio_asset_for_task(task)
        if not asset:
            return None

        request = task.request_payload if isinstance(task.request_payload, dict) else {}
        result = task.result_payload if isinstance(task.result_payload, dict) else {}
        response = task.response_payload if isinstance(task.response_payload, dict) else {}
        audio_id = _first_str([request, result, response], ("audioId", "audio_id", "musicId", "music_id")) or asset.audio_id
        title = asset.display_title or asset.title or (song.title if song else None) or f"video_{asset.id}"

        video = (
            self.db.query(VideoAsset)
            .filter(VideoAsset.suno_task_id == task.task_id, VideoAsset.audio_asset_id == asset.id, VideoAsset.is_deleted.is_(False))
            .order_by(VideoAsset.id.desc())
            .first()
        )
        if not video:
            video = VideoAsset(
                audio_asset_id=asset.id,
                song_id=asset.song_id or (song.id if song else None),
                task_local_id=task.id,
                suno_task_id=task.task_id,
                audio_id=audio_id,
                title=title,
                source_url=video_url,
                status="remote",
                metadata_json={},
            )
        video.source_url = video_url
        video.audio_id = audio_id
        video.song_id = asset.song_id or video.song_id or (song.id if song else None)
        video.title = title
        video.status = "remote" if not video.video_local else video.status
        video.error_message = None
        metadata = dict(video.metadata_json or {})
        metadata.update({
            "provider": "sunoapi",
            "task_type": task.task_type,
            "task_local_id": task.id,
            "suno_task_id": task.task_id,
            "audio_asset_id": asset.id,
            "audio_id": audio_id,
            "video_url_extracted_at": utc_now_naive().isoformat(),
            "request_payload": request,
            "result_payload": result,
        })
        video.metadata_json = metadata
        self.db.add(video)
        self.db.commit()
        self.db.refresh(video)

        if song and video_url and song.video_url != video_url:
            song.video_url = video_url
            self.db.add(song)

        if cache and self.settings.local_content_storage_enabled and self.settings.suno_video_cache_enabled:
            try:
                self.cache_video_asset(video)
            except Exception:
                # Der Task-Erfolg und die Remote-URL bleiben erhalten. Ein
                # fehlgeschlagener lokaler Download wird am VideoAsset sichtbar
                # und kann spaeter per Cache-Endpoint erneut versucht werden.
                pass
        self.db.commit()
        self.db.refresh(video)
        return video

    def _song_for_task(self, task: SunoTask) -> Song | None:
        if task.id:
            asset = self.db.query(AudioAsset).filter(AudioAsset.task_local_id == task.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
            if asset and asset.song_id:
                return self.db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if task.task_id:
            return self.db.query(Song).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).order_by(Song.id.desc()).first()
        return None

    def cache_video_asset(self, video: VideoAsset) -> VideoAsset:
        if not _is_public_http_url(video.source_url):
            raise ValueError("Video-URL ist keine erlaubte öffentliche HTTP(S)-URL.")
        storage = self.settings.video_storage_path
        storage.mkdir(parents=True, exist_ok=True)
        max_bytes = self.settings.video_max_download_bytes
        timeout = httpx.Timeout(float(self.settings.suno_video_download_timeout_seconds), connect=20.0)
        total = 0
        sha = hashlib.sha256()
        tmp_path = storage / f".video_{video.id}_{utc_now_naive().strftime('%Y%m%d_%H%M%S_%f')}.tmp"
        content_type = "video/mp4"
        try:
            with httpx.stream("GET", video.source_url, timeout=timeout, follow_redirects=True, headers={"Accept": "video/mp4,video/*,*/*"}) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "video/mp4").split(";", 1)[0].strip().lower()
                if not _content_type_allowed(content_type):
                    raise ValueError(f"Nicht erlaubter Video-Content-Type: {content_type}")
                with tmp_path.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(f"Video überschreitet {self.settings.suno_video_max_download_mb} MB.")
                        sha.update(chunk)
                        handle.write(chunk)
            if total <= 0:
                raise ValueError("Video-Download lieferte keine Daten.")
            digest = sha.hexdigest()
            extension = _url_extension(video.source_url)
            if extension not in self.settings.video_allowed_extensions_list:
                extension = ".mp4"
            stem = _safe_filename_stem(video.title, f"video_{video.audio_asset_id}_{video.id}")
            final_path = storage / f"video_{video.id}_{stem}_{digest[:16]}{extension}"
            if final_path.exists():
                final_path.unlink()
            tmp_path.replace(final_path)
            video.local_path = to_portable_path(final_path, storage_root=storage)
            video.public_url = public_url_for_file(final_path, storage_root=storage, public_route=self.settings.suno_video_public_route)
            video.filename = final_path.name
            video.content_type = content_type or mimetypes.guess_type(final_path.name)[0] or "video/mp4"
            video.file_size_bytes = total
            video.checksum_sha256 = digest
            video.status = "cached"
            video.error_message = None
            metadata = dict(video.metadata_json or {})
            metadata["cache"] = {
                "cached_at": utc_now_naive().isoformat(),
                "public_url": video.public_url,
                "file_size_bytes": total,
                "checksum_sha256": digest,
                "content_type": video.content_type,
            }
            video.metadata_json = metadata
            self.db.add(video)
            self.db.commit()
            self.db.refresh(video)
            return video
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            video.status = "cache_failed"
            video.error_message = str(exc)
            self.db.add(video)
            self.db.commit()
            self.db.refresh(video)
            raise

    def list_for_audio_asset(self, audio_asset_id: int) -> list[VideoAsset]:
        return (
            self.db.query(VideoAsset)
            .filter(VideoAsset.audio_asset_id == int(audio_asset_id), VideoAsset.is_deleted.is_(False))
            .order_by(VideoAsset.created_at.desc(), VideoAsset.id.desc())
            .all()
        )

    def get_for_audio_asset(self, audio_asset_id: int, video_id: int) -> VideoAsset | None:
        return (
            self.db.query(VideoAsset)
            .filter(VideoAsset.id == int(video_id), VideoAsset.audio_asset_id == int(audio_asset_id), VideoAsset.is_deleted.is_(False))
            .first()
        )

    def resolve_local_path(self, video: VideoAsset) -> Path | None:
        path = resolve_portable_path(video.local_path or video.filename or video.public_url, [self.settings.video_storage_path])
        if path:
            return path
        if video.filename:
            candidate = self.settings.video_storage_path / Path(str(video.filename)).name
            if candidate.exists() and candidate.is_file():
                return candidate
        return None


def attach_video_summaries_to_assets(db: Session, rows: list[AudioAsset]) -> None:
    if not rows:
        return
    asset_ids = [int(row.id) for row in rows if row.id]
    if not asset_ids:
        return
    videos = (
        db.query(VideoAsset)
        .filter(VideoAsset.audio_asset_id.in_(asset_ids), VideoAsset.is_deleted.is_(False))
        .order_by(VideoAsset.audio_asset_id.asc(), VideoAsset.created_at.desc(), VideoAsset.id.desc())
        .all()
    )
    grouped: dict[int, list[VideoAsset]] = {}
    for video in videos:
        grouped.setdefault(int(video.audio_asset_id), []).append(video)
    for row in rows:
        items = grouped.get(int(row.id or 0), [])
        set_committed_value(row, "metadata_json", row.metadata_json or {})
        setattr(row, "video_count", len(items))
        setattr(row, "has_video", bool(items))
        setattr(row, "latest_video", items[0] if items else None)
