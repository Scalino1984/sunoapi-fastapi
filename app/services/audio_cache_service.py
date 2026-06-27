from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AudioAsset, Song, SunoTask
from app.services.id3_tag_service import sync_audio_asset_id3_cover
from app.services.portable_path_service import to_portable_path
from app.utils.time_utils import utc_now_naive


AUDIO_URL_KEYS = {
    "audio_url",
    "audiourl",
    "source_audio_url",
    "sourceaudiourl",
    "stream_audio_url",
    "streamaudiourl",
    "download_url",
    "downloadurl",
    "mp3_url",
    "mp3url",
    "wav_url",
    "wavurl",
    "url",
}

IMAGE_URL_KEYS = {
    "image_url",
    "imageurl",
    "cover_url",
    "coverurl",
    "cover_image_url",
    "coverimageurl",
    "thumbnail_url",
    "thumbnailurl",
    "image",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
AUDIO_ID_KEYS = ("audio_id", "audioId", "id")
TITLE_KEYS = ("title", "name", "songTitle")
DURATION_KEYS = ("duration", "duration_seconds", "durationSeconds")
CREATED_AT_KEYS = (
    "created_at",
    "createdAt",
    "created",
    "created_on",
    "createdOn",
    "create_time",
    "createTime",
    "created_time",
    "createdTime",
    "start_time",
    "startTime",
)
SUCCESS_STATUSES = {"success", "completed", "complete", "finished", "done"}
FIRST_SUCCESS_STATUSES = {"first_success", "firstsuccess"}
MUSIC_TASK_TYPES = {
    "generate_music",
    "extend_music",
    "upload_and_cover",
    "upload_and_extend",
    "add_instrumental",
    "add_vocals",
    "generate_mashup",
    "generate_sounds",
}
CACHEABLE_AUDIO_TASK_TYPES = MUSIC_TASK_TYPES | {
    "separate",
    "convert_to_wav",
}


@dataclass(slots=True)
class AudioCandidate:
    source_url: str
    audio_id: str | None = None
    title: str | None = None
    image_url: str | None = None
    duration_seconds: int | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _normalize_key(key: str) -> str:
    return key.replace("-", "_").replace(" ", "_").lower()


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _url_extension(value: str) -> str:
    return Path(unquote(urlparse(value).path)).suffix.lower()


def _looks_like_image_url(url: str) -> bool:
    return _is_http_url(url) and _url_extension(url) in IMAGE_EXTENSIONS


def _looks_like_audio_url(url: str, allowed_extensions: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    path = unquote(parsed.path).lower()
    extension = Path(path).suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return False

    if extension in allowed_extensions:
        return True

    lowered = url.lower()
    audio_markers = ("audio", "song", "music", "mp3", "wav", "m4a", "flac", "aac", "ogg", "download", "stream")
    return any(marker in lowered for marker in audio_markers)


def _extract_image_url_from_item(item: dict[str, Any]) -> str | None:
    for key, value in item.items():
        if not isinstance(value, str) or not _is_http_url(value):
            continue
        normalized_key = _normalize_key(key)
        if normalized_key in IMAGE_URL_KEYS or _looks_like_image_url(value):
            return value
    return None



def parse_source_datetime(value: Any) -> datetime | None:
    """Normalisiert externe Erstellzeitpunkte aus Suno/SunoAPI-Payloads.

    Unterstützt ISO-Strings, Unix-Sekunden und Unix-Millisekunden. Rückgabe ist
    bewusst naive UTC, passend zu den bestehenden SQLite-DateTime-Feldern.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw <= 0:
            return None
        # Suno/API-Payloads liefern gelegentlich Millisekunden.
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        try:
            dt = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_source_datetime(int(text))
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text[:19] if "%S" in fmt else text[:10], fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def extract_source_created_at(item: dict[str, Any] | None) -> datetime | None:
    if not isinstance(item, dict):
        return None
    for key in CREATED_AT_KEYS:
        parsed = parse_source_datetime(item.get(key))
        if parsed:
            return parsed
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
    if metadata:
        for key in CREATED_AT_KEYS:
            parsed = parse_source_datetime(metadata.get(key))
            if parsed:
                return parsed
    return None

def first_source_created_at(payload: Any) -> datetime | None:
    for item in _walk(payload):
        if not isinstance(item, dict):
            continue
        parsed = extract_source_created_at(item)
        if parsed:
            return parsed
    return None

def collect_audio_candidates(payload: Any) -> list[AudioCandidate]:
    # Ein Suno-sunoData-Objekt kann mehrere URL-Felder enthalten
    # (audioUrl, sourceAudioUrl, streamAudioUrl, sourceStreamAudioUrl).
    # Für die Library darf daraus aber nur EIN AudioAsset pro Variante entstehen.
    from app.services.audio_asset_repair_service import _preferred_audio_url, _preferred_image_url, is_audio_url

    candidates: list[AudioCandidate] = []
    seen: set[tuple[str | None, str]] = set()
    default_created_at = first_source_created_at(payload)

    for item in _walk(payload):
        if not isinstance(item, dict):
            continue

        source_url = _preferred_audio_url(item)
        if not source_url or not is_audio_url(source_url):
            continue

        audio_id = next((str(item.get(key)) for key in AUDIO_ID_KEYS if item.get(key)), None)
        title = next((str(item.get(key)) for key in TITLE_KEYS if item.get(key)), None)
        image_url = _preferred_image_url(item)
        duration = None
        created_at = extract_source_created_at(item) or default_created_at

        for key in DURATION_KEYS:
            try:
                if item.get(key) is not None:
                    duration = int(float(item.get(key)))
                    break
            except (TypeError, ValueError):
                continue

        dedupe_key = (audio_id, source_url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(
            AudioCandidate(
                source_url=source_url,
                audio_id=audio_id,
                title=title,
                image_url=image_url,
                duration_seconds=duration,
                created_at=created_at,
                metadata=item,
            )
        )

    return candidates


def collect_image_urls(payload: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for item in _walk(payload):
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if not isinstance(value, str) or not _is_http_url(value):
                continue
            normalized_key = _normalize_key(key)
            if normalized_key not in IMAGE_URL_KEYS and not _looks_like_image_url(value):
                continue
            if value not in seen:
                seen.add(value)
                urls.append(value)

    return urls


class AudioCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def should_cache_task(self, task: SunoTask) -> bool:
        mode = self.settings.suno_audio_cache_mode.strip().lower()
        if not getattr(self.settings, "local_content_storage_enabled", True):
            return False
        if mode == "off":
            return False
        if self.settings.suno_auto_download_only_music and task.task_type not in CACHEABLE_AUDIO_TASK_TYPES:
            return False
        status = (task.status or "").strip().lower()
        if mode == "on_first_success":
            return status in SUCCESS_STATUSES or status in FIRST_SUCCESS_STATUSES
        if mode == "on_success":
            return status in SUCCESS_STATUSES
        return False

    async def cache_task_audio(self, task: SunoTask, song: Song | None = None) -> list[AudioAsset]:
        candidates = collect_audio_candidates({
            "response_payload": task.response_payload,
            "result_payload": task.result_payload,
        })
        assets: list[AudioAsset] = []

        # Auch wenn der lokale Download deaktiviert oder noch nicht erlaubt ist,
        # müssen AudioAssets existieren. Die Library arbeitet zentral über
        # audio_assets; der Cache-Modus entscheidet nur über lokalen Download.
        if not self.should_cache_task(task):
            for candidate in candidates:
                asset = self._get_or_create_asset(candidate, task=task, song=song)
                if asset.status in {"", "created", "failed"} and not asset.local_path:
                    asset.status = "remote"
                    asset.error_message = None
                    self.db.commit()
                    self.db.refresh(asset)
                assets.append(asset)
            return assets

        for candidate in candidates:
            try:
                assets.append(await self.cache_candidate(candidate, task=task, song=song))
            except Exception as exc:
                failed = self._get_or_create_asset(candidate, task=task, song=song)
                # Download-/Cache-Fehler dürfen die Remote-Verfügbarkeit nicht aus der Library entfernen.
                failed.status = "remote"
                failed.error_message = f"Audio-Cache-Fehler: {exc}"
                failed.image_url = candidate.image_url or failed.image_url
                metadata = failed.metadata_json if isinstance(failed.metadata_json, dict) else {}
                metadata.setdefault("candidate", candidate.metadata or {})
                metadata["audio_cache_error"] = str(exc)
                failed.metadata_json = metadata
                self.db.commit()
                self.db.refresh(failed)
                assets.append(failed)
        return assets

    def _get_or_create_asset(self, candidate: AudioCandidate, task: SunoTask | None, song: Song | None) -> AudioAsset:
        existing = None
        if candidate.audio_id:
            existing = (
                self.db.query(AudioAsset)
                .filter(AudioAsset.audio_id == str(candidate.audio_id), AudioAsset.is_deleted.is_(False))
                .order_by(AudioAsset.id.desc())
                .first()
            )
        if existing is None:
            existing = (
                self.db.query(AudioAsset)
                .filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(False))
                .order_by(AudioAsset.id.desc())
                .first()
            )
        if existing:
            if task and not existing.task_local_id:
                existing.task_local_id = task.id
            if task and not existing.suno_task_id:
                existing.suno_task_id = task.task_id
            if song and not existing.song_id:
                existing.song_id = song.id
            if candidate.image_url and not existing.image_url:
                existing.image_url = candidate.image_url
            if candidate.title and not existing.title:
                existing.title = candidate.title
            request_payload = task.request_payload if task else {}
            if not existing.display_title:
                existing.display_title = candidate.title or (song.title if song else None) or (request_payload or {}).get("title")
            if candidate.created_at:
                metadata = existing.metadata_json if isinstance(existing.metadata_json, dict) else {}
                metadata.setdefault("source_created_at", candidate.created_at.isoformat())
                existing.metadata_json = metadata
                if existing.created_at and existing.created_at > candidate.created_at:
                    existing.created_at = candidate.created_at
            if not existing.operation_label and task:
                existing.operation_label = {
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
                }.get(task.task_type, task.task_type)
            if not existing.parent_audio_id and request_payload:
                existing.parent_audio_id = request_payload.get("audio_id") or request_payload.get("audioId")
            if not existing.parent_task_id and request_payload:
                existing.parent_task_id = request_payload.get("task_id") or request_payload.get("taskId")
            self.db.commit()
            self.db.refresh(existing)
            return existing
        request_payload = task.request_payload if task else {}
        task_type = task.task_type if task else "audio"
        operation_label = {
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
        }.get(task_type, task_type)
        base_title = candidate.title or (song.title if song else None) or (request_payload or {}).get("title")
        parent_audio_id = (request_payload or {}).get("audio_id") or (request_payload or {}).get("audioId")
        parent_task_id = (request_payload or {}).get("task_id") or (request_payload or {}).get("taskId")
        deleted_match = self._has_deleted_asset_match(candidate)
        asset = AudioAsset(
            task_local_id=task.id if task else None,
            song_id=song.id if song else None,
            suno_task_id=task.task_id if task else None,
            audio_id=candidate.audio_id,
            title=candidate.title,
            display_title=base_title,
            operation_label=operation_label,
            parent_audio_id=parent_audio_id,
            parent_task_id=parent_task_id,
            image_url=candidate.image_url,
            source_url=candidate.source_url,
            duration_seconds=candidate.duration_seconds,
            status="remote",
            metadata_json={
                "candidate": candidate.metadata or {},
                "operation": operation_label,
                "request_payload": request_payload or {},
                **({"source_created_at": candidate.created_at.isoformat()} if candidate.created_at else {}),
                **({"recreated_from_deleted_match": True} if deleted_match else {}),
            },
        )
        if candidate.created_at:
            asset.created_at = candidate.created_at
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset


    def _has_deleted_asset_match(self, candidate: AudioCandidate) -> bool:
        if candidate.audio_id:
            if (
                self.db.query(AudioAsset.id)
                .filter(AudioAsset.audio_id == str(candidate.audio_id), AudioAsset.is_deleted.is_(True))
                .first()
            ):
                return True
        if candidate.source_url:
            if (
                self.db.query(AudioAsset.id)
                .filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(True))
                .first()
            ):
                return True
        return False

    def _resolve_cached_file_path(self, value: str | None, *, storage_root: Path | None = None) -> Path | None:
        """Löst portable/absolute lokale Cache-Pfade robust auf.

        Historisch standen hier absolute Pfade, inzwischen portable Werte wie
        storage/audio/datei.mp3 oder nur der Dateiname. Diese Methode verhindert,
        dass ein vorhandener lokaler Cache wegen relativer Pfade erneut geladen
        wird.
        """
        if not value:
            return None
        root = (storage_root or self.settings.audio_storage_path).expanduser().resolve()
        raw = str(value).strip().split("?", 1)[0]
        if not raw:
            return None
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return None
        normalized = unquote(parsed.path if parsed.scheme else raw).replace("\\", "/")
        candidates: list[Path] = []
        candidate = Path(normalized)
        candidates.append(candidate)
        if candidate.name:
            candidates.append(root / candidate.name)
        for marker in ("/storage/audio/", "storage/audio/", "/storage/covers/", "storage/covers/"):
            if marker in normalized:
                rel = normalized.split(marker, 1)[-1].lstrip("/")
                if rel and ".." not in Path(rel).parts:
                    candidates.append(root / rel)
        seen: set[str] = set()
        for item in candidates:
            try:
                resolved = item.expanduser().resolve() if item.is_absolute() else item.expanduser().resolve()
            except Exception:
                try:
                    resolved = (root / item).expanduser().resolve()
                except Exception:
                    continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
                return resolved
        return None

    async def cache_asset_from_candidate(
        self,
        asset: AudioAsset,
        candidate: AudioCandidate,
        task: SunoTask | None = None,
        song: Song | None = None,
    ) -> AudioAsset:
        """Lädt eine bekannte AudioAsset-Variante lokal nach, ohne Duplikate zu erzeugen.

        Diese Methode wird von "Library → Inhalte prüfen" verwendet. Der frühere
        Codepfad rief diese Methode bereits auf, sie fehlte aber im Service. Ein
        fehlender lokaler Cache führte dadurch zu Fehlern statt zu einem Download.
        """
        if not candidate.source_url:
            raise ValueError("Keine Audio-Quelle vorhanden.")

        cached_path = self._resolve_cached_file_path(asset.local_path or asset.filename, storage_root=self.settings.audio_storage_path)
        if asset.status == "cached" and cached_path:
            return asset

        if not asset.source_url:
            asset.source_url = candidate.source_url
        if candidate.audio_id and not asset.audio_id:
            asset.audio_id = candidate.audio_id
        if candidate.title and not asset.title:
            asset.title = candidate.title
        if candidate.title and not asset.display_title:
            asset.display_title = candidate.title
        if candidate.image_url and not asset.image_url:
            asset.image_url = candidate.image_url
        if candidate.duration_seconds and not asset.duration_seconds:
            asset.duration_seconds = candidate.duration_seconds
        if task:
            if not asset.task_local_id:
                asset.task_local_id = task.id
            if not asset.suno_task_id:
                asset.suno_task_id = task.task_id
        if song and not asset.song_id:
            asset.song_id = song.id
        if candidate.created_at:
            metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
            metadata.setdefault("source_created_at", candidate.created_at.isoformat())
            asset.metadata_json = metadata
            if asset.created_at and asset.created_at > candidate.created_at:
                asset.created_at = candidate.created_at

        self._validate_public_url(candidate.source_url)
        storage_dir = self.settings.audio_storage_path
        storage_dir.mkdir(parents=True, exist_ok=True)

        temp_path = storage_dir / f"asset_{asset.id}.download"
        sha256 = hashlib.sha256()
        total_size = 0
        content_type = None

        response, client = await self._open_validated_response(candidate.source_url)
        try:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower() or None
            self._validate_content_type_or_extension(candidate.source_url, content_type)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.settings.audio_max_download_bytes:
                raise ValueError(f"Audiodatei ist zu groß: {content_length} Bytes.")

            with temp_path.open("wb") as fh:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total_size += len(chunk)
                    if total_size > self.settings.audio_max_download_bytes:
                        raise ValueError(f"Audiodatei überschreitet {self.settings.suno_audio_max_download_mb} MB.")
                    sha256.update(chunk)
                    fh.write(chunk)
        finally:
            await response.aclose()
            await client.aclose()

        if total_size <= 0:
            temp_path.unlink(missing_ok=True)
            raise ValueError("Download hat keine Daten geliefert.")

        digest = sha256.hexdigest()
        duplicate = self.db.query(AudioAsset).filter(AudioAsset.checksum_sha256 == digest, AudioAsset.status == "cached", AudioAsset.is_deleted.is_(False)).first()
        extension = self._extension_from_url_or_content_type(candidate.source_url, content_type)
        final_name = f"audio_{asset.id}_{digest[:16]}{extension}"
        final_path = storage_dir / final_name

        duplicate_path = self._resolve_cached_file_path(duplicate.local_path if duplicate else None, storage_root=self.settings.audio_storage_path) if duplicate else None
        if duplicate and duplicate_path:
            temp_path.unlink(missing_ok=True)
            asset.local_path = duplicate.local_path
            asset.public_url = duplicate.public_url
            asset.filename = duplicate.filename
            asset.content_type = duplicate.content_type
            asset.file_size_bytes = duplicate.file_size_bytes
            asset.checksum_sha256 = duplicate.checksum_sha256
            asset.status = "cached"
            asset.error_message = None
            asset.image_url = candidate.image_url or asset.image_url or duplicate.image_url
        else:
            temp_path.replace(final_path)
            asset.local_path = to_portable_path(final_path, storage_root=self.settings.audio_storage_path)
            asset.public_url = f"{self.settings.suno_audio_public_route.rstrip('/')}/{final_name}"
            asset.filename = final_name
            from app.services.audio_metadata_service import normalize_audio_content_type
            asset.content_type = normalize_audio_content_type(content_type, final_path)
            asset.file_size_bytes = total_size
            asset.checksum_sha256 = digest
            asset.status = "cached"
            asset.error_message = None
            asset.image_url = candidate.image_url or asset.image_url

        self.db.commit()
        self.db.refresh(asset)
        return asset

    async def cache_candidate(self, candidate: AudioCandidate, task: SunoTask | None = None, song: Song | None = None) -> AudioAsset:
        asset = self._get_or_create_asset(candidate, task=task, song=song)
        if asset.status == "cached" and asset.local_path and Path(asset.local_path).exists():
            return asset

        self._validate_public_url(candidate.source_url)
        storage_dir = self.settings.audio_storage_path
        storage_dir.mkdir(parents=True, exist_ok=True)

        temp_path = storage_dir / f"asset_{asset.id}.download"
        sha256 = hashlib.sha256()
        total_size = 0
        content_type = None

        response, client = await self._open_validated_response(candidate.source_url)
        try:
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower() or None
            self._validate_content_type_or_extension(candidate.source_url, content_type)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.settings.audio_max_download_bytes:
                raise ValueError(f"Audiodatei ist zu groß: {content_length} Bytes.")

            with temp_path.open("wb") as fh:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total_size += len(chunk)
                    if total_size > self.settings.audio_max_download_bytes:
                        raise ValueError(f"Audiodatei überschreitet {self.settings.suno_audio_max_download_mb} MB.")
                    sha256.update(chunk)
                    fh.write(chunk)
        finally:
            await response.aclose()
            await client.aclose()

        if total_size <= 0:
            raise ValueError("Download hat keine Daten geliefert.")

        digest = sha256.hexdigest()
        duplicate = self.db.query(AudioAsset).filter(AudioAsset.checksum_sha256 == digest, AudioAsset.status == "cached", AudioAsset.is_deleted.is_(False)).first()
        extension = self._extension_from_url_or_content_type(candidate.source_url, content_type)
        final_name = f"audio_{asset.id}_{digest[:16]}{extension}"
        final_path = storage_dir / final_name

        if duplicate and duplicate.local_path and Path(duplicate.local_path).exists():
            temp_path.unlink(missing_ok=True)
            asset.local_path = duplicate.local_path
            asset.public_url = duplicate.public_url
            asset.filename = duplicate.filename
            asset.content_type = duplicate.content_type
            asset.file_size_bytes = duplicate.file_size_bytes
            asset.checksum_sha256 = duplicate.checksum_sha256
            asset.status = "cached"
            asset.error_message = None
            asset.image_url = candidate.image_url or asset.image_url or duplicate.image_url
        else:
            temp_path.replace(final_path)
            asset.local_path = to_portable_path(final_path, storage_root=self.settings.audio_storage_path)
            asset.public_url = f"{self.settings.suno_audio_public_route.rstrip('/')}/{final_name}"
            asset.filename = final_name
            from app.services.audio_metadata_service import normalize_audio_content_type
            asset.content_type = normalize_audio_content_type(content_type, final_path)
            asset.file_size_bytes = total_size
            asset.checksum_sha256 = digest
            asset.status = "cached"
            asset.error_message = None
            asset.image_url = candidate.image_url or asset.image_url

        self.db.commit()
        self.db.refresh(asset)
        return asset

    async def _open_validated_response(self, url: str) -> tuple[httpx.Response, httpx.AsyncClient]:
        current_url = url
        redirects = 0
        client = httpx.AsyncClient(timeout=self.settings.suno_audio_download_timeout_seconds, follow_redirects=False)
        try:
            while True:
                self._validate_public_url(current_url)
                request = client.build_request("GET", current_url, headers={"Accept": "audio/*,*/*"})
                response = await client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        raise ValueError("Redirect ohne Location-Header.")
                    current_url = str(httpx.URL(current_url).join(location))
                    redirects += 1
                    if redirects > 3:
                        raise ValueError("Zu viele Redirects beim Audio-Download.")
                    continue
                response.raise_for_status()
                return response, client
        except Exception:
            await client.aclose()
            raise

    def _validate_public_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Nur öffentliche HTTP/HTTPS-URLs sind erlaubt.")
        host = parsed.hostname
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError(f"Hostname kann nicht aufgelöst werden: {host}") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise ValueError(f"Private oder lokale Zieladresse ist nicht erlaubt: {ip}")

    def _validate_content_type_or_extension(self, url: str, content_type: str | None) -> None:
        extension = Path(urlparse(url).path).suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            raise ValueError(f"Bild-URL wird nicht als Audio verarbeitet: {extension}")
        from app.services.audio_metadata_service import normalize_audio_content_type
        normalized_content_type = normalize_audio_content_type(content_type, None) if content_type else None
        allowed_types = {normalize_audio_content_type(item, None) for item in self.settings.audio_allowed_content_types_list}
        if normalized_content_type and normalized_content_type in allowed_types:
            return
        if extension in self.settings.audio_allowed_extensions_list:
            return
        raise ValueError(f"Nicht erlaubter Audio-Typ: {normalized_content_type or content_type or extension or 'unbekannt'}")

    def _extension_from_url_or_content_type(self, url: str, content_type: str | None) -> str:
        extension = Path(urlparse(url).path).suffix.lower()
        if extension in self.settings.audio_allowed_extensions_list:
            return extension
        mapping = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/aac": ".aac",
            "audio/ogg": ".ogg",
            "audio/flac": ".flac",
        }
        return mapping.get(content_type or "", ".mp3")


@dataclass(slots=True)
class CoverCacheResult:
    source_url: str
    public_url: str
    local_path: str
    filename: str
    checksum_sha256: str
    content_type: str | None = None
    file_size_bytes: int | None = None


class CoverCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def _is_local_cover_url(self, url: str | None) -> bool:
        if not url:
            return False
        route = self.settings.suno_cover_public_route.rstrip("/")
        return str(url).startswith(f"{route}/")

    def _cover_metadata(self, result: CoverCacheResult) -> dict[str, Any]:
        from datetime import datetime
        return {
            "status": "cached",
            "source_url": result.source_url,
            "public_url": result.public_url,
            "local_path": result.local_path,
            "filename": result.filename,
            "checksum_sha256": result.checksum_sha256,
            "content_type": result.content_type,
            "file_size_bytes": result.file_size_bytes,
            "cached_at": utc_now_naive().isoformat(),
        }

    def _merge_cover_metadata(self, metadata: dict[str, Any] | None, result: CoverCacheResult) -> dict[str, Any]:
        merged = dict(metadata or {})
        merged["source_image_url"] = merged.get("source_image_url") or result.source_url
        merged["cover_cache"] = self._cover_metadata(result)
        return merged

    async def cache_task_covers(self, task: SunoTask, song: Song | None = None) -> list[CoverCacheResult]:
        if not self.settings.suno_cover_cache_enabled:
            return []

        payload = {
            "response_payload": task.response_payload,
            "result_payload": task.result_payload,
        }
        urls = collect_image_urls(payload)
        results: list[CoverCacheResult] = []

        # Song-Cover zuerst sichern, damit Songdetails und Projektgruppen sofort die lokale URL nutzen.
        if song and song.cover_image_url and _is_http_url(song.cover_image_url) and not self._is_local_cover_url(song.cover_image_url):
            if song.cover_image_url not in urls:
                urls.insert(0, song.cover_image_url)

        seen: set[str] = set()
        for url in urls:
            if url in seen or self._is_local_cover_url(url):
                continue
            seen.add(url)
            try:
                result = await self.cache_cover_url(url)
            except Exception:
                continue
            results.append(result)

            if song and (song.cover_image_url == url or not song.cover_image_url or not self._is_local_cover_url(song.cover_image_url)):
                song.cover_image_url = result.public_url
                song.metadata_json = self._merge_cover_metadata(song.metadata_json if isinstance(song.metadata_json, dict) else {}, result)

            if task.task_id:
                assets = (
                    self.db.query(AudioAsset)
                    .filter(AudioAsset.suno_task_id == task.task_id, AudioAsset.is_deleted.is_(False))
                    .all()
                )
                for asset in assets:
                    if asset.image_url == url or (not asset.image_url and result.source_url):
                        asset.image_url = result.public_url
                        asset.metadata_json = self._merge_cover_metadata(asset.metadata_json if isinstance(asset.metadata_json, dict) else {}, result)
                        sync_audio_asset_id3_cover(asset, Path(result.local_path), title=asset.display_title or asset.title or asset.filename)

        if results:
            self.db.commit()
            if song:
                self.db.refresh(song)
        return results

    async def cache_asset_cover(self, asset: AudioAsset, image_url: str | None = None) -> CoverCacheResult | None:
        if not self.settings.suno_cover_cache_enabled:
            return None
        source_url = image_url or asset.image_url
        if not source_url or not _is_http_url(source_url) or self._is_local_cover_url(source_url):
            return None
        result = await self.cache_cover_url(source_url)
        asset.image_url = result.public_url
        asset.metadata_json = self._merge_cover_metadata(asset.metadata_json if isinstance(asset.metadata_json, dict) else {}, result)
        sync_audio_asset_id3_cover(asset, Path(result.local_path), title=asset.display_title or asset.title or asset.filename)
        self.db.commit()
        self.db.refresh(asset)
        return result

    async def cache_song_cover(self, song: Song, image_url: str | None = None) -> CoverCacheResult | None:
        if not self.settings.suno_cover_cache_enabled:
            return None
        source_url = image_url or song.cover_image_url
        if not source_url or not _is_http_url(source_url) or self._is_local_cover_url(source_url):
            return None
        result = await self.cache_cover_url(source_url)
        song.cover_image_url = result.public_url
        song.metadata_json = self._merge_cover_metadata(song.metadata_json if isinstance(song.metadata_json, dict) else {}, result)
        self.db.commit()
        self.db.refresh(song)
        return result

    async def cache_cover_url(self, url: str) -> CoverCacheResult:
        if not self.settings.suno_cover_cache_enabled:
            raise ValueError("Cover-Cache ist deaktiviert.")
        self._validate_public_url(url)
        storage_dir = self.settings.cover_storage_path
        storage_dir.mkdir(parents=True, exist_ok=True)

        temp_path = storage_dir / "cover.download"
        sha256 = hashlib.sha256()
        total_size = 0
        content_type = None

        response, client = await self._open_validated_image_response(url)
        try:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower() or None
            self._validate_content_type_or_extension(url, content_type)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.settings.cover_max_download_bytes:
                raise ValueError(f"Cover ist zu groß: {content_length} Bytes.")

            with temp_path.open("wb") as fh:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    total_size += len(chunk)
                    if total_size > self.settings.cover_max_download_bytes:
                        raise ValueError(f"Cover überschreitet {self.settings.suno_cover_max_download_mb} MB.")
                    sha256.update(chunk)
                    fh.write(chunk)
        finally:
            await response.aclose()
            await client.aclose()

        if total_size <= 0:
            raise ValueError("Cover-Download hat keine Daten geliefert.")

        digest = sha256.hexdigest()
        extension = self._extension_from_url_or_content_type(url, content_type)
        final_name = f"cover_{digest[:16]}{extension}"
        final_path = storage_dir / final_name
        if final_path.exists() and final_path.stat().st_size > 0:
            temp_path.unlink(missing_ok=True)
        else:
            temp_path.replace(final_path)

        return CoverCacheResult(
            source_url=url,
            public_url=f"{self.settings.suno_cover_public_route.rstrip('/')}/{final_name}",
            local_path=to_portable_path(final_path, storage_root=self.settings.cover_storage_path),
            filename=final_name,
            checksum_sha256=digest,
            content_type=content_type,
            file_size_bytes=total_size,
        )

    async def _open_validated_image_response(self, url: str) -> tuple[httpx.Response, httpx.AsyncClient]:
        current_url = url
        redirects = 0
        client = httpx.AsyncClient(timeout=self.settings.suno_cover_download_timeout_seconds, follow_redirects=False)
        try:
            while True:
                self._validate_public_url(current_url)
                request = client.build_request("GET", current_url, headers={"Accept": "image/*,*/*"})
                response = await client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        raise ValueError("Redirect ohne Location-Header.")
                    current_url = str(httpx.URL(current_url).join(location))
                    redirects += 1
                    if redirects > 3:
                        raise ValueError("Zu viele Redirects beim Cover-Download.")
                    continue
                response.raise_for_status()
                return response, client
        except Exception:
            await client.aclose()
            raise

    def _validate_public_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Nur öffentliche HTTP/HTTPS-URLs sind erlaubt.")
        host = parsed.hostname
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError(f"Hostname kann nicht aufgelöst werden: {host}") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise ValueError(f"Private oder lokale Zieladresse ist nicht erlaubt: {ip}")

    def _validate_content_type_or_extension(self, url: str, content_type: str | None) -> None:
        extension = Path(urlparse(url).path).suffix.lower()
        allowed_extensions = set(self.settings.cover_allowed_extensions_list)
        allowed_types = set(self.settings.cover_allowed_content_types_list)
        if content_type and content_type in allowed_types:
            return
        if extension in allowed_extensions:
            return
        raise ValueError(f"Nicht erlaubter Cover-Typ: {content_type or extension or 'unbekannt'}")

    def _extension_from_url_or_content_type(self, url: str, content_type: str | None) -> str:
        extension = Path(urlparse(url).path).suffix.lower()
        if extension in self.settings.cover_allowed_extensions_list:
            return extension
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
        }
        return mapping.get(content_type or "", ".jpg")
