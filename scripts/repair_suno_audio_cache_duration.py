#!/usr/bin/env python3
"""Repair locally cached Suno audio assets whose stored file is wrong or stale.

Examples from project root:
    python3 scripts/repair_suno_audio_cache_duration.py --dry-run
    python3 scripts/repair_suno_audio_cache_duration.py --asset-id 355 --force --dry-run
    python3 scripts/repair_suno_audio_cache_duration.py --asset-id 355 --force
    python3 scripts/repair_suno_audio_cache_duration.py --asset-id 355 --audio-url 'https://...mp3' --force

Rules:
- Lyrics/SRT timing stays DB-based.
- Audio cache repair always prefers the official final SunoAPI audio_url over source/stream URLs.
- Explicit --force clears the stale local cache reference before re-downloading, because otherwise
  AudioCacheService may correctly skip already cached files.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import AudioAsset, Song, SunoTask
from app.services.audio_cache_service import AudioCacheService, AudioCandidate
from app.services.audio_metadata_service import read_audio_duration_seconds

# Official SunoAPI callback field priority for generated audio.
# Do NOT prefer sourceAudioUrl/source_audio_url for generated songs: that can be
# the uploaded/original/source audio or a non-final stream and can produce wrong local duration.
AUDIO_URL_PREFERENCE = (
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
)
IMAGE_URL_PREFERENCE = (
    "imageUrl",
    "image_url",
    "coverImageUrl",
    "cover_image_url",
    "sourceImageUrl",
    "source_image_url",
    "thumbnailUrl",
    "thumbnail_url",
)
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


@dataclass(slots=True)
class CandidateHit:
    source_url: str
    image_url: str | None
    duration_seconds: int | None
    metadata: dict[str, Any]
    origin: str
    matched_audio_id: bool = False


def _is_http_url(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_audio_url(value: str | None) -> bool:
    if not _is_http_url(value):
        return False
    path = urlparse(str(value)).path.lower()
    return path.endswith(AUDIO_EXTENSIONS) or "audio" in path or "tempfile" in str(value).lower()


def _looks_like_image_url(value: str | None) -> bool:
    if not _is_http_url(value):
        return False
    return urlparse(str(value)).path.lower().endswith(IMAGE_EXTENSIONS)


def _preferred_audio_url(item: dict[str, Any]) -> str | None:
    for key in AUDIO_URL_PREFERENCE:
        value = item.get(key)
        if isinstance(value, str) and _looks_like_audio_url(value):
            return value.strip()
    for key, value in item.items():
        if not isinstance(value, str):
            continue
        normalized = key.replace("-", "_").lower()
        if any(bad in normalized for bad in ("image", "cover", "thumbnail", "video")):
            continue
        if normalized in {"url", "src", "href"} and _looks_like_audio_url(value):
            return value.strip()
    return None


def _preferred_image_url(item: dict[str, Any]) -> str | None:
    for key in IMAGE_URL_PREFERENCE:
        value = item.get(key)
        if isinstance(value, str) and _is_http_url(value):
            return value.strip()
    for key, value in item.items():
        if isinstance(value, str) and _looks_like_image_url(value):
            return value.strip()
    return None


def _duration_value(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        parsed = int(round(float(value)))
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _duration_from_item(item: dict[str, Any]) -> int | None:
    for key in ("duration", "duration_seconds", "durationSeconds", "audioDuration", "audio_duration"):
        value = _duration_value(item.get(key))
        if value:
            return value
    return None


def _walk_named(value: Any, origin: str) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield origin, value
        for key, child in value.items():
            child_origin = f"{origin}.{key}" if origin else str(key)
            yield from _walk_named(child, child_origin)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_named(child, f"{origin}[{index}]")


def _metadata(asset: AudioAsset) -> dict[str, Any]:
    return asset.metadata_json if isinstance(asset.metadata_json, dict) else {}


def _candidate_dict(asset: AudioAsset) -> dict[str, Any]:
    candidate = _metadata(asset).get("candidate")
    return candidate if isinstance(candidate, dict) else {}


def _audio_id_matches(asset: AudioAsset, item: dict[str, Any]) -> bool:
    wanted = str(asset.audio_id or "").strip()
    if not wanted:
        return False
    for key in ("id", "audioId", "audio_id", "song_id", "clip_id"):
        if str(item.get(key) or "").strip() == wanted:
            return True
    return False


def _task_for_asset(db, asset: AudioAsset) -> SunoTask | None:
    if asset.task_local_id:
        task = db.query(SunoTask).filter(SunoTask.id == asset.task_local_id).first()
        if task:
            return task
    if asset.suno_task_id:
        return db.query(SunoTask).filter(SunoTask.task_id == asset.suno_task_id).order_by(SunoTask.id.desc()).first()
    return None


def _song_for_asset(db, asset: AudioAsset) -> Song | None:
    if not asset.song_id:
        return None
    return db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()


def _candidate_hits(asset: AudioAsset, task: SunoTask | None, song: Song | None) -> list[CandidateHit]:
    payloads: list[tuple[str, Any]] = [
        ("asset.metadata.candidate", _candidate_dict(asset)),
        ("asset.metadata", _metadata(asset)),
    ]
    if task:
        payloads.extend([
            ("task.result_payload", task.result_payload),
            ("task.response_payload", task.response_payload),
            ("task.request_payload", task.request_payload),
        ])
    if song:
        payloads.extend([
            ("song.metadata", song.metadata_json),
            ("song", {
                "audioUrl": song.audio_url,
                "imageUrl": song.cover_image_url,
                "duration": getattr(song, "duration_seconds", None),
            }),
        ])

    hits: list[CandidateHit] = []
    seen_urls: set[str] = set()
    for origin, payload in payloads:
        for item_origin, item in _walk_named(payload, origin):
            url = _preferred_audio_url(item)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            hits.append(CandidateHit(
                source_url=url,
                image_url=_preferred_image_url(item) or asset.image_url,
                duration_seconds=_duration_from_item(item),
                metadata=item,
                origin=item_origin,
                matched_audio_id=_audio_id_matches(asset, item),
            ))

    if asset.source_url and _looks_like_audio_url(asset.source_url) and asset.source_url not in seen_urls:
        hits.append(CandidateHit(
            source_url=asset.source_url,
            image_url=asset.image_url,
            duration_seconds=_duration_value(asset.duration_seconds),
            metadata=_metadata(asset),
            origin="asset.source_url fallback",
            matched_audio_id=False,
        ))

    def score(hit: CandidateHit) -> tuple[int, int]:
        # Prefer exact audio_id match, then official final audio_url fields, then any fallback.
        official_score = 0
        for index, key in enumerate(AUDIO_URL_PREFERENCE):
            if hit.metadata.get(key) == hit.source_url:
                official_score = len(AUDIO_URL_PREFERENCE) - index
                break
        return (1000 if hit.matched_audio_id else 0) + official_score, 1 if hit.duration_seconds else 0

    return sorted(hits, key=score, reverse=True)


def _expected_duration(asset: AudioAsset, hit: CandidateHit | None) -> int | None:
    if hit and hit.duration_seconds:
        return hit.duration_seconds
    candidate = _candidate_dict(asset)
    for source in (candidate, _metadata(asset)):
        if isinstance(source, dict):
            value = _duration_from_item(source)
            if value:
                return value
    # Last fallback only; can already be polluted by a bad local file.
    return _duration_value(asset.duration_seconds)


def _duration_mismatch(expected: int | None, actual: int | None) -> bool:
    if not expected or not actual:
        return False
    tolerance = max(4.0, float(expected) * 0.05)
    return abs(float(expected) - float(actual)) > tolerance


def _local_path(service: AudioCacheService, asset: AudioAsset) -> Path | None:
    return service._resolve_cached_file_path(asset.local_path or asset.filename, storage_root=service.settings.audio_storage_path)


def _ids_from_args(asset_ids: list[int] | None, ids_csv: str | None) -> list[int]:
    result = list(asset_ids or [])
    if ids_csv:
        for part in ids_csv.split(","):
            part = part.strip()
            if part:
                result.append(int(part))
    return sorted(set(result))


def _print_asset_debug(asset: AudioAsset, path: Path | None, actual: int | None, expected: int | None, hits: list[CandidateHit]) -> None:
    print(
        f"ASSET asset_id={asset.id} status={asset.status} audio_id={asset.audio_id or '-'} "
        f"db_duration={asset.duration_seconds or '-'} expected={expected or '-'} local={actual or '-'} "
        f"file={path or '-'}"
    )
    print(f"  source_url={asset.source_url or '-'}")
    for index, hit in enumerate(hits[:8], start=1):
        marker = "MATCH" if hit.matched_audio_id else "cand"
        print(f"  {index}. {marker} duration={hit.duration_seconds or '-'} origin={hit.origin} url={hit.source_url}")


def _make_candidate(asset: AudioAsset, hit: CandidateHit) -> AudioCandidate:
    return AudioCandidate(
        source_url=hit.source_url,
        audio_id=asset.audio_id,
        title=asset.display_title or asset.title,
        image_url=hit.image_url or asset.image_url,
        duration_seconds=hit.duration_seconds,
        metadata=hit.metadata or _metadata(asset),
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Repair stale/corrupt Suno local audio cache files.")
    parser.add_argument("--dry-run", action="store_true", help="Only report; do not re-download.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of assets to scan when no --asset-id is given.")
    parser.add_argument("--asset-id", action="append", type=int, help="Target one asset id. Can be used multiple times.")
    parser.add_argument("--ids", help="Comma-separated asset ids.")
    parser.add_argument("--audio-url", help="Override official audio URL for a targeted repair.")
    parser.add_argument("--force", action="store_true", help="Re-download targeted asset even if DB/local durations do not show a mismatch.")
    parser.add_argument("--verbose", action="store_true", help="Print candidate URL selection details.")
    args = parser.parse_args()

    target_ids = _ids_from_args(args.asset_id, args.ids)
    if args.audio_url and not target_ids:
        parser.error("--audio-url requires --asset-id or --ids")

    db = SessionLocal()
    try:
        service = AudioCacheService(db)
        if target_ids:
            rows = (
                db.query(AudioAsset)
                .filter(AudioAsset.id.in_(target_ids), AudioAsset.is_deleted.is_(False))
                .order_by(AudioAsset.id.desc())
                .all()
            )
        else:
            rows = (
                db.query(AudioAsset)
                .filter(AudioAsset.is_deleted.is_(False), AudioAsset.status == "cached")
                .order_by(AudioAsset.id.desc())
                .limit(max(1, args.limit))
                .all()
            )

        found_ids = {int(row.id) for row in rows}
        missing_ids = [asset_id for asset_id in target_ids if asset_id not in found_ids]
        for asset_id in missing_ids:
            print(f"NOT_FOUND asset_id={asset_id}")

        scanned = repaired = mismatched = skipped = forced = 0
        for asset in rows:
            scanned += 1
            task = _task_for_asset(db, asset)
            song = _song_for_asset(db, asset)
            hits = _candidate_hits(asset, task, song)
            if args.audio_url:
                hits.insert(0, CandidateHit(
                    source_url=args.audio_url.strip(),
                    image_url=asset.image_url,
                    duration_seconds=None,
                    metadata={"audioUrl": args.audio_url.strip()},
                    origin="--audio-url",
                    matched_audio_id=True,
                ))
            hit = hits[0] if hits else None
            expected = _expected_duration(asset, hit)
            path = _local_path(service, asset)
            actual = read_audio_duration_seconds(path) if path else None
            mismatch = _duration_mismatch(expected, actual)
            force_this = bool(args.force and target_ids and int(asset.id) in target_ids)

            if args.verbose or target_ids:
                _print_asset_debug(asset, path, actual, expected, hits)

            if not mismatch and not force_this:
                continue
            if force_this:
                forced += 1
            else:
                mismatched += 1
            reason = "force" if force_this and not mismatch else "mismatch"
            print(f"REPAIR_CANDIDATE asset_id={asset.id} reason={reason} expected={expected or '-'}s local={actual or '-'}s file={path or '-'}")

            if not hit:
                skipped += 1
                print(f"  SKIP asset_id={asset.id}: keine offizielle audio_url/source_url gefunden")
                continue

            print(f"  USE_URL origin={hit.origin} url={hit.source_url}")
            if args.dry_run:
                continue

            # Force re-download: cache_asset_from_candidate intentionally skips already cached assets.
            old_path = path
            asset.source_url = hit.source_url
            asset.local_path = None
            asset.public_url = None
            asset.filename = None
            asset.content_type = None
            asset.file_size_bytes = None
            asset.checksum_sha256 = None
            asset.status = "remote"
            asset.error_message = None
            if hit.duration_seconds:
                asset.duration_seconds = hit.duration_seconds
            db.commit()
            db.refresh(asset)

            candidate = _make_candidate(asset, hit)
            await service.cache_asset_from_candidate(asset, candidate, task=task, song=song)
            db.refresh(asset)
            new_path = _local_path(service, asset)
            new_duration = read_audio_duration_seconds(new_path) if new_path else None
            if new_duration:
                asset.duration_seconds = int(round(new_duration))
                db.commit()
                db.refresh(asset)
            print(f"  REPAIRED asset_id={asset.id} new_duration={new_duration or '-'}s file={new_path or '-'} old_file={old_path or '-'}")
            repaired += 1

        print(
            f"DONE scanned={scanned} mismatched={mismatched} forced={forced} "
            f"repaired={repaired} skipped={skipped} dry_run={args.dry_run}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
