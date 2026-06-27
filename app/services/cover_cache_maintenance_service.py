from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AudioAsset, AudioProject, Song
from app.services.audio_cache_service import CoverCacheResult, CoverCacheService
from app.services.id3_tag_service import sync_audio_asset_id3_cover
from app.utils.time_utils import utc_now_naive


@dataclass(slots=True)
class CoverReference:
    source_url: str
    table: str
    id: int
    field: str
    audio_asset_id: int | None = None
    title: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CoverCacheMaintenanceResult:
    ok: bool
    dry_run: bool
    checked: int = 0
    candidate_urls: int = 0
    reference_count: int = 0
    downloaded: int = 0
    updated_references: int = 0
    failed: int = 0
    skipped: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_local_cover_url(value: str | None) -> bool:
    if not value:
        return False
    route = get_settings().suno_cover_public_route.rstrip("/")
    return str(value).startswith(f"{route}/")


def _cover_metadata(result: CoverCacheResult) -> dict[str, Any]:
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


def _merge_cover_metadata(metadata: Any, result: CoverCacheResult) -> dict[str, Any]:
    merged = dict(metadata or {}) if isinstance(metadata, dict) else {}
    merged["source_image_url"] = merged.get("source_image_url") or result.source_url
    merged["cover_cache"] = _cover_metadata(result)
    return merged


def collect_external_cover_references(db: Session, *, limit: int = 200) -> list[CoverReference]:
    references: list[CoverReference] = []

    def add(source_url: str | None, table: str, row_id: int, field: str, *, audio_asset_id: int | None = None, title: str | None = None) -> None:
        if not _is_http_url(source_url) or _is_local_cover_url(source_url):
            return
        references.append(
            CoverReference(
                source_url=str(source_url).strip(),
                table=table,
                id=int(row_id),
                field=field,
                audio_asset_id=audio_asset_id,
                title=title,
            )
        )

    for asset in (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .filter(AudioAsset.image_url.isnot(None))
        .order_by(AudioAsset.id.asc())
        .all()
    ):
        add(asset.image_url, "audio_assets", asset.id, "image_url", audio_asset_id=asset.id, title=asset.display_title or asset.title)

    for song in (
        db.query(Song)
        .filter(Song.is_deleted.is_(False))
        .filter(Song.cover_image_url.isnot(None))
        .order_by(Song.id.asc())
        .all()
    ):
        add(song.cover_image_url, "songs", song.id, "cover_image_url", title=song.title)

    for project in (
        db.query(AudioProject)
        .filter(AudioProject.is_deleted.is_(False))
        .filter(AudioProject.cover_image_url.isnot(None))
        .order_by(AudioProject.id.asc())
        .all()
    ):
        add(project.cover_image_url, "audio_projects", project.id, "cover_image_url", title=project.title)

    if limit > 0:
        # Limit gilt auf eindeutige URLs, Referenzen derselben URL bleiben zusammen.
        seen_urls: set[str] = set()
        limited: list[CoverReference] = []
        for reference in references:
            if reference.source_url not in seen_urls:
                if len(seen_urls) >= limit:
                    continue
                seen_urls.add(reference.source_url)
            limited.append(reference)
        return limited
    return references


async def cache_external_cover_references(db: Session, *, dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    """Sichert externe Cover-URLs lokal und ersetzt DB-Referenzen durch /media/covers.

    Die Funktion ändert keine Audio-Identität. Konkrete Audio-Bezüge laufen, wo
    vorhanden, über ``audio_asset_id``. Downloads nutzen die bestehende
    CoverCacheService-Validierung gegen private/lokale Zieladressen.
    """
    references = collect_external_cover_references(db, limit=max(1, int(limit or 50)))
    grouped: dict[str, list[CoverReference]] = {}
    for reference in references:
        grouped.setdefault(reference.source_url, []).append(reference)

    result = CoverCacheMaintenanceResult(
        ok=True,
        dry_run=dry_run,
        checked=len(references),
        candidate_urls=len(grouped),
        reference_count=len(references),
        examples=[reference.as_dict() for reference in references[:10]],
    )
    if dry_run:
        return result.as_dict()

    service = CoverCacheService(db)
    for source_url, refs in grouped.items():
        try:
            cached = await service.cache_cover_url(source_url)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.ok = False
            if len(result.errors) < 10:
                result.errors.append({"source_url": source_url, "error": f"{exc.__class__.__name__}: {exc}"})
            continue

        result.downloaded += 1
        local_cover_path = get_settings().cover_storage_path / cached.filename
        for ref in refs:
            updated = False
            if ref.table == "audio_assets":
                asset = db.query(AudioAsset).filter(AudioAsset.id == ref.id, AudioAsset.is_deleted.is_(False)).first()
                if asset and asset.image_url == source_url:
                    asset.image_url = cached.public_url
                    asset.metadata_json = _merge_cover_metadata(asset.metadata_json, cached)
                    db.add(asset)
                    sync_audio_asset_id3_cover(asset, local_cover_path, title=asset.display_title or asset.title or asset.filename)
                    updated = True
            elif ref.table == "songs":
                song = db.query(Song).filter(Song.id == ref.id, Song.is_deleted.is_(False)).first()
                if song and song.cover_image_url == source_url:
                    song.cover_image_url = cached.public_url
                    song.metadata_json = _merge_cover_metadata(song.metadata_json, cached)
                    db.add(song)
                    updated = True
            elif ref.table == "audio_projects":
                project = db.query(AudioProject).filter(AudioProject.id == ref.id, AudioProject.is_deleted.is_(False)).first()
                if project and project.cover_image_url == source_url:
                    project.cover_image_url = cached.public_url
                    metadata = dict(project.metadata_json or {}) if isinstance(project.metadata_json, dict) else {}
                    metadata["source_image_url"] = metadata.get("source_image_url") or source_url
                    metadata["cover_cache"] = _cover_metadata(cached)
                    project.metadata_json = metadata
                    db.add(project)
                    updated = True
            if updated:
                result.updated_references += 1
            else:
                result.skipped += 1

        db.commit()

    return result.as_dict()
