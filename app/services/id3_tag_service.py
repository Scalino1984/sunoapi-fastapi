from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AudioAsset, AudioProject, Song
from app.utils.time_utils import utc_now_naive

try:
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2
except Exception:  # pragma: no cover - mutagen ist als Runtime-Dependency definiert.
    APIC = ID3 = ID3NoHeaderError = TIT2 = None  # type: ignore[assignment]


SUPPORTED_AUDIO_SUFFIXES = {".mp3"}
SUPPORTED_COVER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _metadata_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_title(value: Any) -> str:
    return str(value or "").strip()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _path_from_value(value: Any, root: Path, public_route: str) -> list[Path]:
    if not value:
        return []
    raw = str(value).strip().split("?", 1)[0]
    if not raw:
        return []
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return []

    normalized = unquote(parsed.path if parsed.scheme else raw).replace("\\", "/")
    candidates: list[Path] = []
    direct = Path(normalized)
    candidates.append(direct)
    if direct.name:
        candidates.append(root / direct.name)

    route = public_route.rstrip("/")
    if route and normalized.startswith(route + "/"):
        relative = normalized[len(route):].lstrip("/")
        if relative and ".." not in Path(relative).parts:
            candidates.append(root / relative)

    return candidates


def resolve_audio_asset_mp3_path(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    root = settings.audio_storage_path.expanduser().resolve()
    candidates: list[Path] = []

    for value in (asset.local_path, asset.filename, asset.public_url):
        candidates.extend(_path_from_value(value, root, settings.suno_audio_public_route))

    if root.exists():
        if asset.id:
            candidates.extend(sorted(root.glob(f"audio_{asset.id}_*.mp3")))
            candidates.extend(sorted(root.glob(f"*_{asset.id}_*.mp3")))
        if asset.filename:
            candidates.extend(sorted(root.rglob(Path(str(asset.filename)).name)))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            path = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).expanduser().resolve()
        except Exception:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not _is_relative_to(path, root):
            continue
        if path.exists() and path.is_file() and path.stat().st_size > 0 and path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES:
            return path
    return None


def resolve_cover_image_path(value: Any) -> Path | None:
    settings = get_settings()
    root = settings.cover_storage_path.expanduser().resolve()
    public_route = settings.suno_cover_public_route
    candidates = _path_from_value(value, root, public_route)

    metadata = value if isinstance(value, dict) else {}
    for key in ("local_path", "path", "filename", "public_url", "cover_url"):
        candidates.extend(_path_from_value(metadata.get(key), root, public_route))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            path = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).expanduser().resolve()
        except Exception:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not _is_relative_to(path, root):
            continue
        if path.exists() and path.is_file() and path.stat().st_size > 0 and path.suffix.lower() in SUPPORTED_COVER_SUFFIXES:
            return path
    return None


def _cover_mime_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed in {"image/jpeg", "image/png", "image/webp"}:
        return guessed
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _load_id3_tags(path: Path) -> ID3:
    if ID3 is None or ID3NoHeaderError is None:
        raise RuntimeError("mutagen.id3 ist nicht verfügbar.")
    try:
        return ID3(path)
    except ID3NoHeaderError:
        return ID3()


def _write_id3_tags(path: Path, tags: ID3) -> None:
    try:
        tags.save(path, v2_version=3)
    except TypeError:
        tags.save(path)


def write_mp3_title(audio_path: Path, title: str) -> dict[str, Any]:
    clean_title = _safe_title(title)
    if not clean_title:
        return {"updated": False, "reason": "empty_title", "path": str(audio_path)}
    if audio_path.suffix.lower() != ".mp3":
        return {"updated": False, "reason": "unsupported_audio_format", "path": str(audio_path)}
    tags = _load_id3_tags(audio_path)
    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=[clean_title]))
    _write_id3_tags(audio_path, tags)
    return {"updated": True, "field": "TIT2", "title": clean_title, "path": str(audio_path), "updated_at": utc_now_naive().isoformat()}


def write_mp3_cover(audio_path: Path, cover_path: Path, *, title: str | None = None) -> dict[str, Any]:
    if audio_path.suffix.lower() != ".mp3":
        return {"updated": False, "reason": "unsupported_audio_format", "path": str(audio_path)}
    if not cover_path.exists() or not cover_path.is_file() or cover_path.stat().st_size <= 0:
        return {"updated": False, "reason": "cover_file_missing", "path": str(audio_path), "cover_path": str(cover_path)}
    tags = _load_id3_tags(audio_path)
    tags.delall("APIC")
    tags.add(APIC(
        encoding=3,
        mime=_cover_mime_type(cover_path),
        type=3,
        desc="Cover",
        data=cover_path.read_bytes(),
    ))
    clean_title = _safe_title(title)
    if clean_title:
        tags.delall("TIT2")
        tags.add(TIT2(encoding=3, text=[clean_title]))
    _write_id3_tags(audio_path, tags)
    return {
        "updated": True,
        "fields": ["APIC", "TIT2"] if clean_title else ["APIC"],
        "title": clean_title or None,
        "path": str(audio_path),
        "cover_path": str(cover_path),
        "cover_mime_type": _cover_mime_type(cover_path),
        "cover_size_bytes": cover_path.stat().st_size,
        "updated_at": utc_now_naive().isoformat(),
    }


def _store_id3_result(asset: AudioAsset, result: dict[str, Any], *, key: str) -> None:
    metadata = dict(asset.metadata_json or {})
    id3_meta = dict(metadata.get("id3_tags") or {})
    id3_meta[key] = result
    metadata["id3_tags"] = id3_meta
    asset.metadata_json = metadata


def sync_audio_asset_id3_title(asset: AudioAsset, title: str) -> dict[str, Any]:
    audio_path = resolve_audio_asset_mp3_path(asset)
    if not audio_path:
        result = {"updated": False, "reason": "local_mp3_not_found", "audio_asset_id": asset.id, "title": _safe_title(title)}
        _store_id3_result(asset, result, key="title")
        return result
    try:
        result = write_mp3_title(audio_path, title)
    except Exception as exc:
        result = {"updated": False, "reason": "id3_write_failed", "error": str(exc), "audio_asset_id": asset.id, "path": str(audio_path), "title": _safe_title(title)}
    _store_id3_result(asset, result, key="title")
    return result


def sync_audio_asset_id3_cover(asset: AudioAsset, cover_path: Path, *, title: str | None = None) -> dict[str, Any]:
    audio_path = resolve_audio_asset_mp3_path(asset)
    if not audio_path:
        result = {"updated": False, "reason": "local_mp3_not_found", "audio_asset_id": asset.id, "cover_path": str(cover_path), "title": _safe_title(title)}
        _store_id3_result(asset, result, key="cover")
        return result
    try:
        result = write_mp3_cover(audio_path, cover_path, title=title)
    except Exception as exc:
        result = {"updated": False, "reason": "id3_write_failed", "error": str(exc), "audio_asset_id": asset.id, "path": str(audio_path), "cover_path": str(cover_path), "title": _safe_title(title)}
    _store_id3_result(asset, result, key="cover")
    return result


def sync_song_assets_id3_title(db: Session, song: Song, title: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for asset in db.query(AudioAsset).filter(AudioAsset.song_id == song.id, AudioAsset.is_deleted.is_(False)).all():
        results.append(sync_audio_asset_id3_title(asset, title))
        db.add(asset)
    return results


def sync_project_assets_id3_title(db: Session, project: AudioProject, title: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for asset in db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).all():
        results.append(sync_audio_asset_id3_title(asset, title))
        db.add(asset)
    return results
