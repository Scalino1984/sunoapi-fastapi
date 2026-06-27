from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import AudioAsset, AudioProject, Song, SunoTask
from app.services.audio_asset_materialization_service import OPERATION_LABELS
from app.services.audio_asset_repair_service import is_bad_image_asset, is_audio_url, repair_local_file_metadata
from app.services.audio_cache_service import AudioCacheService, AudioCandidate, CACHEABLE_AUDIO_TASK_TYPES, CoverCacheService, collect_audio_candidates, collect_image_urls, first_source_created_at, parse_source_datetime
from app.utils.time_utils import utc_now_naive

SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}


@dataclass(slots=True)
class SongLibrarySyncResult:
    ok: bool = True
    dry_run: bool = True
    checked_songs: int = 0
    songs_with_candidates: int = 0
    candidates_found: int = 0
    created: int = 0
    updated: int = 0
    skipped_deleted: int = 0
    recreated_deleted_matches: int = 0
    source_date_updates: int = 0
    project_updates: int = 0
    checked_tasks: int = 0
    tasks_with_candidates: int = 0
    task_only_created: int = 0
    external_task_ids_checked: int = 0
    external_task_ids_missing: int = 0
    external_task_imported: int = 0
    external_task_already_local: int = 0
    external_task_import_failed: int = 0
    external_task_examples: list[dict[str, Any]] = field(default_factory=list)
    source_rows_checked: int = 0
    source_rows_imported: int = 0
    source_rows_skipped_existing: int = 0
    source_rows_failed: int = 0
    created_tasks: int = 0
    created_songs: int = 0
    covers_cached: int = 0
    cached_audio_files: int = 0
    cache_failed: int = 0
    warnings: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed_total(self) -> int:
        return int(
            self.created
            + self.updated
            + self.source_date_updates
            + self.project_updates
            + self.task_only_created
            + self.external_task_imported
            + self.source_rows_imported
            + self.created_tasks
            + self.created_songs
            + self.covers_cached
            + self.cached_audio_files
        )

    def add_example(self, payload: dict[str, Any]) -> None:
        if len(self.examples) < 8:
            self.examples.append(payload)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_total"] = self.changed_total
        return payload


def source_datetime_from_song(song: Song) -> datetime | None:
    """Extract the best external Suno/SunoAPI date from a Song row.

    /api/music/songs already exposes Song.metadata_json. In that metadata the
    original SunoAPI result usually contains data.response.sunoData[].createTime.
    This helper keeps sorting stable by preferring that source date over local
    insert/update timestamps.
    """
    metadata = song.metadata_json if isinstance(song.metadata_json, dict) else {}
    parsed = first_source_created_at(metadata)
    if parsed:
        return parsed
    for source in (
        metadata,
        metadata.get("result_payload") if isinstance(metadata.get("result_payload"), dict) else None,
        metadata.get("response_payload") if isinstance(metadata.get("response_payload"), dict) else None,
        metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else None,
    ):
        if not isinstance(source, dict):
            continue
        for key in ("source_created_at", "created_at", "createdAt", "created", "createTime"):
            parsed = parse_source_datetime(source.get(key))
            if parsed:
                return parsed
    return None


def song_sort_datetime(song: Song) -> datetime:
    return source_datetime_from_song(song) or song.created_at or song.updated_at or datetime.min


class SongLibrarySyncService:
    """Synchronizes the central audio_assets library from local Song rows.

    The primary source is the /api/music/songs payload. Local rows are
    repaired into audio_assets. Optional external /api/music/songs JSON from
    another instance is imported deterministically: task_id exists -> skip;
    task_id missing -> create local SunoTask + Song + AudioAssets, then cache
    audio/cover according to the existing cache settings. No new provider path
    is introduced.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._task_cache: dict[str, SunoTask | None] = {}

    def sync_from_songs(self, *, limit: int = 1000, dry_run: bool = True) -> SongLibrarySyncResult:
        result = SongLibrarySyncResult(dry_run=bool(dry_run))
        safe_limit = max(1, min(int(limit or 1000), 5000))
        rows = (
            self.db.query(Song)
            .filter(Song.is_deleted.is_(False))
            .order_by(Song.created_at.desc(), Song.id.desc())
            .limit(safe_limit)
            .all()
        )
        for song in rows:
            result.checked_songs += 1
            candidates = self._song_candidates(song)
            if not candidates:
                continue
            result.songs_with_candidates += 1
            result.candidates_found += len(candidates)

            task = self._task_for_song(song)
            for candidate in candidates:
                if not candidate.source_url or not is_audio_url(candidate.source_url):
                    continue
                asset = self._find_active_asset(candidate)
                deleted_match = asset is None and self._has_deleted_match(candidate)
                if asset is None:
                    result.created += 1
                    if deleted_match:
                        result.recreated_deleted_matches += 1
                    result.add_example({
                        "song_id": song.id,
                        "title": song.title,
                        "audio_id": candidate.audio_id,
                        "source_url": candidate.source_url,
                        "action": "recreate_audio_asset_after_deleted_match" if deleted_match else "create_audio_asset",
                        "source_created_at": candidate.created_at.isoformat() if candidate.created_at else None,
                    })
                    if not dry_run:
                        asset = self._create_asset(song, candidate, task, recreated_from_deleted_match=deleted_match)
                        if self._assign_project(asset, song):
                            result.project_updates += 1
                    continue

                source_date_would_change = bool(candidate.created_at and asset.created_at != candidate.created_at)
                changed = self._update_asset(asset, song, candidate, task, dry_run=dry_run)
                if changed:
                    result.updated += 1
                    result.add_example({
                        "song_id": song.id,
                        "audio_asset_id": asset.id,
                        "title": song.title,
                        "audio_id": candidate.audio_id,
                        "action": "update_audio_asset",
                        "source_date_update": source_date_would_change,
                    })
                if source_date_would_change:
                    # _update_asset() handles the actual write; count is separated
                    # so the UI can show that newest-first source sorting changed.
                    result.source_date_updates += 1

            if self._sync_song_source_date(song, candidates, dry_run=dry_run):
                result.source_date_updates += 1

        if dry_run:
            self.db.rollback()
        else:
            self.db.commit()
        return result

    async def sync_from_songs_and_cache(
        self,
        *,
        limit: int = 1000,
        dry_run: bool = True,
        task_ids: list[str] | None = None,
        source_songs: Any | None = None,
        source_json: str | None = None,
        task_type: str = "generate_music",
    ) -> SongLibrarySyncResult:
        """Synchronisiert lokale Song-/Task-Daten und erzwingt den lokalen Cache bei on_success.

        Die Route ist der zentrale Sync-Pfad für die lokale Library.
        Sie synchronisiert lokale Song-/Task-Daten und kann optional konkrete
        externe SunoAPI.org-Task-IDs nachziehen. Diese Task-IDs können direkt
        als Liste/Text oder als komplette /api/music/songs-JSON-Antwort einer
        anderen App-Instanz übergeben werden. Es wird weiterhin kein neuer
        Provider-Weg erstellt: der Import läuft über MusicService.import_external_task()
        und damit über den vorhandenen SunoAPIClient/Record-Info-Pfad.
        """
        safe_limit = max(1, min(int(limit or 1000), 5000))
        result = self.sync_from_songs(limit=safe_limit, dry_run=dry_run)

        source_rows = self.extract_source_song_rows(source_songs=source_songs, source_json=source_json)
        imported_from_source_rows = 0
        if source_rows:
            imported_from_source_rows = await self._import_external_source_rows(
                source_rows,
                result=result,
                dry_run=dry_run,
                task_type=task_type or "generate_music",
            )

        external_task_ids = self.extract_task_ids(task_ids=task_ids, source_songs=None if source_rows else source_songs, source_json=None if source_rows else source_json)
        if external_task_ids:
            await self._import_external_task_ids(
                external_task_ids,
                result=result,
                dry_run=dry_run,
                task_type=task_type or "generate_music",
            )
            # Nach externen Task-Imports erneut lokale Songs/Tasks in AudioAssets
            # zusammenführen. So landen frisch importierte Task-Ergebnisse sofort
            # in der Library und bekommen das originale Suno-Datum.
            if not dry_run and result.external_task_imported:
                second_pass = self.sync_from_songs(limit=safe_limit, dry_run=False)
                self._merge_second_pass(result, second_pass)

        if not dry_run and imported_from_source_rows:
            second_pass = self.sync_from_songs(limit=safe_limit, dry_run=False)
            self._merge_second_pass(result, second_pass)

        if dry_run:
            return result
        await self._cache_successful_task_audio(limit=safe_limit, result=result)
        self.db.commit()
        return result


    @staticmethod
    def _load_source_payload(source_songs: Any | None = None, source_json: str | None = None) -> Any | None:
        if source_songs is not None:
            return source_songs
        raw = str(source_json or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    @classmethod
    def extract_source_song_rows(cls, *, source_songs: Any | None = None, source_json: str | None = None) -> list[dict[str, Any]]:
        """Return concrete /api/music/songs rows from pasted JSON.

        A row is only accepted when it contains a task_id/taskId and enough
        result metadata to contain SunoData. This prevents accidental import of
        nested candidate dictionaries as independent songs.
        """
        payload = cls._load_source_payload(source_songs=source_songs, source_json=source_json)
        rows: list[dict[str, Any]] = []

        def looks_like_song_row(item: dict[str, Any]) -> bool:
            if not isinstance(item, dict):
                return False
            task_id = cls._row_task_id(item)
            if not task_id:
                return False
            if "metadata_json" in item or "audio_url" in item or "cover_image_url" in item:
                return True
            result_payload = item.get("result_payload") if isinstance(item.get("result_payload"), dict) else None
            return bool(result_payload and collect_audio_candidates(result_payload))

        def walk(value: Any) -> None:
            if isinstance(value, list):
                for child in value:
                    walk(child)
                return
            if not isinstance(value, dict):
                return
            if looks_like_song_row(value):
                rows.append(value)
                return
            for key in ("songs", "items", "results", "data"):
                child = value.get(key)
                if isinstance(child, (list, dict)):
                    walk(child)

        walk(payload)
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            task_id = cls._row_task_id(row)
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            unique.append(row)
        return unique

    @staticmethod
    def extract_task_ids(*, task_ids: Any | None = None, source_songs: Any | None = None, source_json: str | None = None) -> list[str]:
        """Extract SunoAPI.org task IDs from direct text/list or /api/music/songs JSON.

        This intentionally extracts task IDs only. It does not trust remote DB
        rows as local truth. The actual import still fetches official
        SunoAPI.org record-info by taskId through the existing MusicService.
        """
        values: list[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return
                # Accept raw task IDs, comma/newline separated values and small
                # copied snippets containing task_id/taskId. SunoAPI task IDs in
                # this app are commonly hex-like, but we keep this conservative
                # enough to avoid URLs and UUID clip IDs becoming task IDs.
                for match in re.findall(r"(?<![A-Za-z0-9_-])([A-Za-z0-9]{16,64})(?![A-Za-z0-9_-])", text):
                    values.append(match.strip())
                return
            if isinstance(value, dict):
                for key in ("task_id", "taskId", "suno_task_id"):
                    add(value.get(key))
                metadata = value.get("metadata_json") if isinstance(value.get("metadata_json"), dict) else None
                if metadata:
                    add(metadata)
                for key in ("request_payload", "response_payload", "result_payload"):
                    payload = value.get(key) if isinstance(value.get(key), dict) else None
                    if payload:
                        add(payload)
                data = value.get("data") if isinstance(value.get("data"), dict) else None
                if data:
                    add(data)
                response = value.get("response") if isinstance(value.get("response"), dict) else None
                if response:
                    add(response)
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    add(item)

        add(task_ids)
        add(source_songs)
        if source_json:
            raw = str(source_json or "").strip()
            if raw:
                try:
                    add(json.loads(raw))
                except Exception:
                    add(raw)

        seen: set[str] = set()
        result: list[str] = []
        for item in values:
            task_id = str(item or "").strip()
            if not task_id or task_id in seen:
                continue
            # Avoid importing Suno public clip UUIDs here. Those belong to the
            # public clip import endpoint, not SunoAPI task record-info.
            if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", task_id):
                continue
            seen.add(task_id)
            result.append(task_id)
        return result

    @staticmethod
    def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
        return row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}

    @staticmethod
    def _row_task_id(row: dict[str, Any]) -> str | None:
        for key in ("task_id", "taskId", "suno_task_id"):
            value = row.get(key)
            if value:
                return str(value).strip()
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
        for source in (
            metadata,
            metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else None,
            metadata.get("response_payload") if isinstance(metadata.get("response_payload"), dict) else None,
            metadata.get("result_payload") if isinstance(metadata.get("result_payload"), dict) else None,
        ):
            if not isinstance(source, dict):
                continue
            for key in ("task_id", "taskId", "suno_task_id"):
                if source.get(key):
                    return str(source.get(key)).strip()
            data = source.get("data") if isinstance(source.get("data"), dict) else None
            if data and data.get("taskId"):
                return str(data.get("taskId")).strip()
        return None

    @staticmethod
    def _safe_json_loads(value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _row_result_payload(cls, row: dict[str, Any], task_id: str) -> dict[str, Any]:
        metadata = cls._row_metadata(row)
        result_payload = metadata.get("result_payload") if isinstance(metadata.get("result_payload"), dict) else None
        if isinstance(result_payload, dict) and result_payload:
            return dict(result_payload)
        if isinstance(row.get("result_payload"), dict):
            return dict(row["result_payload"])
        # Fallback: build a minimal successful result from the row itself.
        candidate = {
            "id": row.get("audio_id") or row.get("id"),
            "audioUrl": row.get("audio_url"),
            "imageUrl": row.get("source_image_url") or row.get("cover_image_url"),
            "title": row.get("title"),
            "prompt": row.get("prompt") or row.get("lyrics"),
            "modelName": row.get("model_name") or row.get("model"),
            "duration": row.get("duration_seconds"),
        }
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "taskId": task_id,
                "response": {"taskId": task_id, "sunoData": [candidate]},
                "status": "SUCCESS",
                "operationType": "generate",
            },
        }

    @classmethod
    def _row_response_payload(cls, row: dict[str, Any], task_id: str) -> dict[str, Any]:
        metadata = cls._row_metadata(row)
        response_payload = metadata.get("response_payload") if isinstance(metadata.get("response_payload"), dict) else None
        if isinstance(response_payload, dict) and response_payload:
            return dict(response_payload)
        return {"source": "song_library_source_json_import", "taskId": task_id, "taskType": "generate_music"}

    @classmethod
    def _row_request_payload(cls, row: dict[str, Any], result_payload: dict[str, Any], task_id: str) -> dict[str, Any]:
        metadata = cls._row_metadata(row)
        request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
        request = dict(request_payload or {})
        data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
        param = cls._safe_json_loads(data.get("param"))
        # Prefer concrete param values for missing/empty manual import placeholders.
        for key, value in param.items():
            if value is not None and value != "" and not request.get(key):
                request[key] = value
        request.setdefault("source", "song_library_source_json_import")
        request.setdefault("task_id", task_id)
        request.setdefault("task_type", "generate_music")
        return request

    @classmethod
    def _source_datetime_from_row(cls, row: dict[str, Any]) -> datetime | None:
        metadata = cls._row_metadata(row)
        for source in (metadata, row):
            parsed = first_source_created_at(source)
            if parsed:
                return parsed
            for key in ("source_created_at", "created_at", "createdAt", "createTime", "updated_at"):
                parsed = parse_source_datetime(source.get(key)) if isinstance(source, dict) else None
                if parsed:
                    return parsed
        return None

    @classmethod
    def _source_image_url_from_row(cls, row: dict[str, Any], result_payload: dict[str, Any]) -> str | None:
        metadata = cls._row_metadata(row)
        cover_cache = metadata.get("cover_cache") if isinstance(metadata.get("cover_cache"), dict) else {}
        for value in (
            metadata.get("source_image_url"),
            cover_cache.get("source_url"),
            row.get("source_image_url"),
            row.get("cover_image_url"),
        ):
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        urls = collect_image_urls(result_payload)
        return urls[0] if urls else None

    async def _import_external_source_rows(
        self,
        source_rows: list[dict[str, Any]],
        *,
        result: SongLibrarySyncResult,
        dry_run: bool,
        task_type: str,
    ) -> int:
        """Import missing tasks directly from a /api/music/songs JSON response.

        This is the simple deterministic path the UI calls "Songs → Library
        synchronisieren": task_id already exists -> skip; task_id missing ->
        persist task + song, materialize every sunoData entry as AudioAsset,
        cache audio and cover with the existing AudioCache/CoverCache services.
        """
        imported = 0
        audio_cache = AudioCacheService(self.db)
        cover_cache = CoverCacheService(self.db)

        for row in source_rows:
            result.source_rows_checked += 1
            task_id = self._row_task_id(row)
            if not task_id:
                result.source_rows_failed += 1
                if len(result.warnings) < 20:
                    result.warnings.append("Quelle enthält einen Song ohne task_id; Eintrag übersprungen.")
                continue

            result.external_task_ids_checked += 1
            existing = self._local_task_or_content_exists(task_id)
            if existing:
                result.external_task_already_local += 1
                result.source_rows_skipped_existing += 1
                self._add_external_task_example({"task_id": task_id, "action": "skip_existing_task_id", **existing}, result)
                continue

            result.external_task_ids_missing += 1
            result_payload = self._row_result_payload(row, task_id)
            request_payload = self._row_request_payload(row, result_payload, task_id)
            candidates = collect_audio_candidates(result_payload)
            if not candidates:
                result.source_rows_failed += 1
                result.external_task_import_failed += 1
                self._add_external_task_example({"task_id": task_id, "action": "source_json_no_audio_candidates"}, result)
                continue

            if dry_run:
                self._add_external_task_example({
                    "task_id": task_id,
                    "action": "would_import_source_json",
                    "candidates": len(candidates),
                    "title": row.get("title") or request_payload.get("title") or (candidates[0].title if candidates else None),
                }, result)
                continue

            try:
                source_dt = self._source_datetime_from_row(row) or first_source_created_at(result_payload)
                data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
                status = str(data.get("status") or row.get("status") or "SUCCESS")
                resolved_task_type = str(request_payload.get("task_type") or task_type or "generate_music")
                task = SunoTask(
                    task_id=task_id,
                    task_type=resolved_task_type,
                    status=status,
                    request_payload=request_payload,
                    response_payload=self._row_response_payload(row, task_id),
                    result_payload=result_payload,
                    error_message=data.get("errorMessage") if isinstance(data, dict) else None,
                    started_at=source_dt,
                    heartbeat_at=utc_now_naive(),
                    completed_at=source_dt if status.upper() in SUCCESS_STATUSES else None,
                )
                if source_dt:
                    task.created_at = source_dt
                    task.updated_at = source_dt
                self.db.add(task)
                self.db.flush()
                result.created_tasks += 1

                first_candidate = candidates[0]
                first_meta = first_candidate.metadata if isinstance(first_candidate.metadata, dict) else {}
                title = row.get("title") or request_payload.get("title") or first_candidate.title or "Unbenannt"
                prompt = row.get("prompt") or row.get("lyrics") or request_payload.get("prompt") or first_meta.get("prompt")
                model = row.get("model") or request_payload.get("model") or first_meta.get("modelName") or first_meta.get("model")
                source_image_url = self._source_image_url_from_row(row, result_payload)
                metadata = dict(self._row_metadata(row))
                metadata["import_source"] = metadata.get("import_source") or "song_library_source_json_import"
                metadata["source_json_task_id"] = task_id
                if source_dt:
                    metadata["source_created_at"] = source_dt.isoformat()
                if source_image_url:
                    metadata["source_image_url"] = source_image_url

                song = Song(
                    title=title,
                    model=model,
                    prompt=prompt,
                    lyrics=row.get("lyrics"),
                    audio_url=row.get("audio_url") or first_candidate.source_url,
                    cover_image_url=source_image_url or row.get("cover_image_url"),
                    video_url=row.get("video_url"),
                    midi_url=row.get("midi_url"),
                    wav_url=row.get("wav_url"),
                    task_id=task_id,
                    metadata_json=metadata,
                )
                if source_dt:
                    song.created_at = source_dt
                    song.updated_at = source_dt
                self.db.add(song)
                self.db.flush()
                result.created_songs += 1

                assets_before = {
                    row_id for (row_id,) in self.db.query(AudioAsset.id).filter(AudioAsset.suno_task_id == task_id, AudioAsset.is_deleted.is_(False)).all()
                }
                assets = await audio_cache.cache_task_audio(task, song=song)
                assets_after = [asset for asset in assets if asset.id not in assets_before]
                result.created += len(assets_after)
                cached_count = sum(1 for asset in assets if str(asset.status or "").lower() == "cached")
                result.cached_audio_files += cached_count

                covers = await cover_cache.cache_task_covers(task, song=song)
                result.covers_cached += len(covers)
                self.db.flush()

                imported += 1
                result.external_task_imported += 1
                result.source_rows_imported += 1
                self._add_external_task_example({
                    "task_id": task_id,
                    "task_local_id": task.id,
                    "song_id": song.id,
                    "audio_assets": len(assets),
                    "cached_audio_files": cached_count,
                    "covers_cached": len(covers),
                    "action": "imported_from_source_json",
                }, result)
            except Exception as exc:
                self.db.rollback()
                result.source_rows_failed += 1
                result.external_task_import_failed += 1
                message = f"Source-JSON-Import für Task {task_id} fehlgeschlagen: {exc}"
                if len(result.warnings) < 20:
                    result.warnings.append(message)
                self._add_external_task_example({"task_id": task_id, "action": "source_json_import_failed", "error": str(exc)}, result)

        if not dry_run and imported:
            self.db.commit()
        elif dry_run:
            self.db.rollback()
        return imported

    async def _import_external_task_ids(
        self,
        task_ids: list[str],
        *,
        result: SongLibrarySyncResult,
        dry_run: bool,
        task_type: str,
    ) -> None:
        from app.services.music_service import MusicService

        service = MusicService(self.db)
        for task_id in task_ids:
            result.external_task_ids_checked += 1
            existing = self._local_task_or_content_exists(task_id)
            if existing:
                result.external_task_already_local += 1
                self._add_external_task_example({
                    "task_id": task_id,
                    "action": "already_local",
                    **existing,
                }, result)
                continue

            result.external_task_ids_missing += 1
            if dry_run:
                self._add_external_task_example({"task_id": task_id, "action": "would_import_from_sunoapi"}, result)
                continue

            try:
                imported_task = await service.import_external_task({
                    "task_id": task_id,
                    "task_type": task_type or "generate_music",
                    "cache_audio": True,
                })
                import_status = str(getattr(imported_task, "import_status", "") or "")
                already = bool(getattr(imported_task, "already_imported", False)) or import_status == "already_imported"
                if already:
                    result.external_task_already_local += 1
                    action = "already_imported_after_check"
                else:
                    result.external_task_imported += 1
                    action = "imported_from_sunoapi"
                self._add_external_task_example({
                    "task_id": task_id,
                    "task_local_id": getattr(imported_task, "id", None),
                    "status": getattr(imported_task, "status", None),
                    "action": action,
                }, result)
            except Exception as exc:
                result.external_task_import_failed += 1
                message = f"SunoAPI.org Task-Import {task_id} fehlgeschlagen: {exc}"
                if len(result.warnings) < 20:
                    result.warnings.append(message)
                self._add_external_task_example({"task_id": task_id, "action": "import_failed", "error": str(exc)}, result)

    def _local_task_or_content_exists(self, task_id: str) -> dict[str, Any] | None:
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.desc()).first()
        song = self.db.query(Song).filter(Song.task_id == task_id, Song.is_deleted.is_(False)).order_by(Song.id.desc()).first()
        asset = self.db.query(AudioAsset).filter(AudioAsset.suno_task_id == task_id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        if not task and not song and not asset:
            return None
        return {
            "task_local_id": task.id if task else None,
            "song_id": song.id if song else None,
            "audio_asset_id": asset.id if asset else None,
        }

    @staticmethod
    def _merge_second_pass(result: SongLibrarySyncResult, second: SongLibrarySyncResult) -> None:
        result.checked_songs += second.checked_songs
        result.songs_with_candidates += second.songs_with_candidates
        result.candidates_found += second.candidates_found
        result.created += second.created
        result.updated += second.updated
        result.skipped_deleted += second.skipped_deleted
        result.recreated_deleted_matches += second.recreated_deleted_matches
        result.source_date_updates += second.source_date_updates
        result.project_updates += second.project_updates
        for warning in second.warnings:
            if len(result.warnings) < 20:
                result.warnings.append(warning)
        for example in second.examples:
            result.add_example(example)

    @staticmethod
    def _add_external_task_example(payload: dict[str, Any], result: SongLibrarySyncResult) -> None:
        if len(result.external_task_examples) < 8:
            result.external_task_examples.append(payload)

    async def _cache_successful_task_audio(self, *, limit: int, result: SongLibrarySyncResult) -> None:
        cache_service = AudioCacheService(self.db)
        tasks = (
            self.db.query(SunoTask)
            .filter(SunoTask.is_deleted.is_(False))
            .filter(SunoTask.task_type.in_(CACHEABLE_AUDIO_TASK_TYPES))
            .order_by(SunoTask.created_at.desc(), SunoTask.id.desc())
            .limit(limit)
            .all()
        )

        for task in tasks:
            result.checked_tasks += 1
            if not cache_service.should_cache_task(task):
                continue
            candidates = collect_audio_candidates({
                "response_payload": task.response_payload,
                "result_payload": task.result_payload,
            })
            candidates = [item for item in candidates if item.source_url and is_audio_url(item.source_url)]
            if not candidates:
                continue
            result.tasks_with_candidates += 1
            song = self._song_for_task(task)

            for candidate in candidates:
                asset = self._find_active_asset(candidate)
                try:
                    if asset is None:
                        cached_asset = await cache_service.cache_candidate(candidate, task=task, song=song)
                        result.task_only_created += 1
                        result.cached_audio_files += 1 if cached_asset.status == "cached" else 0
                        result.add_example({
                            "task_local_id": task.id,
                            "suno_task_id": task.task_id,
                            "audio_id": candidate.audio_id,
                            "action": "cache_create_from_success_task",
                            "status": cached_asset.status,
                        })
                        continue

                    before_status = asset.status
                    before_local_path = asset.local_path
                    cached_asset = await cache_service.cache_asset_from_candidate(asset, candidate, task=task, song=song)
                    if cached_asset.status == "cached" and (before_status != "cached" or before_local_path != cached_asset.local_path):
                        result.cached_audio_files += 1
                        result.add_example({
                            "task_local_id": task.id,
                            "audio_asset_id": cached_asset.id,
                            "audio_id": candidate.audio_id,
                            "action": "cache_existing_from_success_task",
                            "local_path": cached_asset.local_path,
                        })
                except Exception as exc:
                    result.cache_failed += 1
                    message = f"Audio-Cache für Task {task.id} / {candidate.audio_id or candidate.source_url} fehlgeschlagen: {exc}"
                    if len(result.warnings) < 20:
                        result.warnings.append(message)
                    if asset is not None:
                        asset.status = "remote" if not asset.local_path else asset.status
                        asset.error_message = message
                        self.db.add(asset)
                        self.db.commit()

    def _song_for_task(self, task: SunoTask) -> Song | None:
        task_id = str(task.task_id or "").strip()
        if not task_id:
            return None
        return (
            self.db.query(Song)
            .filter(Song.task_id == task_id, Song.is_deleted.is_(False))
            .order_by(Song.id.desc())
            .first()
        )

    def _song_candidates(self, song: Song) -> list[AudioCandidate]:
        metadata = song.metadata_json if isinstance(song.metadata_json, dict) else {}
        candidates = collect_audio_candidates(metadata)
        # Deduplicate by actual audio source first. Some legacy payloads contain
        # the same clip twice: once with audio_id and once without audio_id. Keeping
        # both creates false HIGH audit findings and repeated skipped/deleted hits.
        by_source: dict[str, AudioCandidate] = {}
        by_audio_id: set[str] = set()
        for candidate in candidates:
            if not candidate.source_url or not is_audio_url(candidate.source_url):
                continue
            source_key = str(candidate.source_url).strip()
            audio_key = str(candidate.audio_id).strip() if candidate.audio_id else ""
            if audio_key and audio_key in by_audio_id:
                continue
            existing = by_source.get(source_key)
            if existing is None:
                by_source[source_key] = candidate
                if audio_key:
                    by_audio_id.add(audio_key)
                continue
            # Prefer the richer candidate that carries the Suno clip id.
            if not existing.audio_id and candidate.audio_id:
                by_source[source_key] = candidate
                by_audio_id.add(audio_key)
        return list(by_source.values())

    def _task_for_song(self, song: Song) -> SunoTask | None:
        task_id = str(song.task_id or "").strip()
        if not task_id:
            return None
        if task_id not in self._task_cache:
            self._task_cache[task_id] = (
                self.db.query(SunoTask)
                .filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False))
                .order_by(SunoTask.id.desc())
                .first()
            )
        return self._task_cache.get(task_id)

    def _find_active_asset(self, candidate: AudioCandidate) -> AudioAsset | None:
        if candidate.audio_id:
            rows = (
                self.db.query(AudioAsset)
                .filter(AudioAsset.audio_id == str(candidate.audio_id), AudioAsset.is_deleted.is_(False))
                .all()
            )
            rows = [row for row in rows if not is_bad_image_asset(row)]
            if rows:
                return sorted(rows, key=lambda row: (row.status == "cached", row.id or 0), reverse=True)[0]
        if candidate.source_url:
            return (
                self.db.query(AudioAsset)
                .filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(False))
                .order_by(AudioAsset.id.desc())
                .first()
            )
        return None

    def _has_deleted_match(self, candidate: AudioCandidate) -> bool:
        if candidate.audio_id:
            if self.db.query(AudioAsset.id).filter(AudioAsset.audio_id == str(candidate.audio_id), AudioAsset.is_deleted.is_(True)).first():
                return True
        if candidate.source_url:
            if self.db.query(AudioAsset.id).filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(True)).first():
                return True
        return False

    def _operation_label(self, song: Song, task: SunoTask | None) -> str:
        metadata = song.metadata_json if isinstance(song.metadata_json, dict) else {}
        result_payload = metadata.get("result_payload") if isinstance(metadata.get("result_payload"), dict) else {}
        data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
        operation_type = data.get("operationType") or result_payload.get("operationType")
        task_type = task.task_type if task else None
        return OPERATION_LABELS.get(str(task_type or operation_type or "generate_music"), str(operation_type or task_type or "Generiert"))

    def _request_payload(self, song: Song, task: SunoTask | None) -> dict[str, Any]:
        if task and isinstance(task.request_payload, dict) and task.request_payload:
            return dict(task.request_payload)
        metadata = song.metadata_json if isinstance(song.metadata_json, dict) else {}
        request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
        if request_payload:
            return dict(request_payload)
        return {
            "title": song.title,
            "model": song.model,
            "prompt": song.prompt,
            "lyrics": song.lyrics,
        }

    def _base_metadata(self, song: Song, candidate: AudioCandidate, task: SunoTask | None) -> dict[str, Any]:
        metadata = {
            "candidate": candidate.metadata or {},
            "request_payload": self._request_payload(song, task),
            "operation": self._operation_label(song, task),
            "materialized_by": "song_library_sync_service",
            "song_sync_source": "/api/music/songs",
        }
        if candidate.created_at:
            metadata["source_created_at"] = candidate.created_at.isoformat()
        return metadata

    def _create_asset(self, song: Song, candidate: AudioCandidate, task: SunoTask | None, *, recreated_from_deleted_match: bool = False) -> AudioAsset:
        display_title = candidate.title or song.title or "Unbenannt"
        asset = AudioAsset(
            task_local_id=task.id if task else None,
            song_id=song.id,
            suno_task_id=song.task_id or (task.task_id if task else None),
            audio_id=str(candidate.audio_id) if candidate.audio_id else None,
            title=candidate.title,
            display_title=display_title,
            image_url=candidate.image_url or song.cover_image_url,
            source_url=candidate.source_url,
            duration_seconds=candidate.duration_seconds,
            status="remote",
            operation_label=self._operation_label(song, task),
            content_type="audio/mpeg" if str(candidate.source_url).lower().split("?", 1)[0].endswith(".mp3") else None,
            metadata_json={
                **self._base_metadata(song, candidate, task),
                **({"recreated_from_deleted_match": True} if recreated_from_deleted_match else {}),
            },
            project_id=song.project_id,
        )
        if candidate.created_at:
            asset.created_at = candidate.created_at
            asset.updated_at = candidate.created_at
        self.db.add(asset)
        self.db.flush()
        repair_local_file_metadata(asset)
        self.db.add(asset)
        return asset

    def _update_asset(self, asset: AudioAsset, song: Song, candidate: AudioCandidate, task: SunoTask | None, *, dry_run: bool) -> bool:
        updates: dict[str, Any] = {}
        if not asset.song_id:
            updates["song_id"] = song.id
        if task and not asset.task_local_id:
            updates["task_local_id"] = task.id
        if not asset.suno_task_id and (song.task_id or (task.task_id if task else None)):
            updates["suno_task_id"] = song.task_id or task.task_id
        if not asset.audio_id and candidate.audio_id:
            updates["audio_id"] = str(candidate.audio_id)
        if not asset.title and candidate.title:
            updates["title"] = candidate.title
        if not asset.display_title:
            updates["display_title"] = candidate.title or song.title or "Unbenannt"
        if not asset.image_url and (candidate.image_url or song.cover_image_url):
            updates["image_url"] = candidate.image_url or song.cover_image_url
        if candidate.duration_seconds and not asset.duration_seconds:
            updates["duration_seconds"] = candidate.duration_seconds
        if not asset.operation_label:
            updates["operation_label"] = self._operation_label(song, task)
        if str(asset.status or "").lower() in {"", "created", "failed"} and not asset.local_path:
            updates["status"] = "remote"
            updates["error_message"] = None
        if candidate.created_at and asset.created_at != candidate.created_at:
            updates["created_at"] = candidate.created_at

        existing_meta = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
        new_meta = dict(existing_meta)
        if candidate.metadata and new_meta.get("candidate") != candidate.metadata:
            new_meta["candidate"] = candidate.metadata
        request_payload = self._request_payload(song, task)
        if request_payload and new_meta.get("request_payload") != request_payload:
            new_meta["request_payload"] = request_payload
        operation = self._operation_label(song, task)
        if new_meta.get("operation") != operation:
            new_meta["operation"] = operation
        if new_meta.get("song_sync_source") != "/api/music/songs":
            new_meta["song_sync_source"] = "/api/music/songs"
        if not new_meta.get("materialized_by"):
            new_meta["materialized_by"] = "song_library_sync_service"
        if candidate.created_at and new_meta.get("source_created_at") != candidate.created_at.isoformat():
            new_meta["source_created_at"] = candidate.created_at.isoformat()
        if new_meta != existing_meta:
            updates["metadata_json"] = new_meta

        if not updates:
            return False
        if dry_run:
            return True
        for key, value in updates.items():
            setattr(asset, key, value)
        if repair_local_file_metadata(asset):
            pass
        self.db.add(asset)
        self._assign_project(asset, song)
        return True

    def _assign_project(self, asset: AudioAsset, song: Song) -> bool:
        if asset.project_id:
            if not song.project_id:
                song.project_id = asset.project_id
                self.db.add(song)
                return True
            return False
        project = None
        if song.project_id:
            project = self.db.query(AudioProject).filter(AudioProject.id == song.project_id, AudioProject.is_deleted.is_(False)).first()
        if project is None:
            project = (
                self.db.query(AudioProject)
                .join(AudioAsset, AudioAsset.project_id == AudioProject.id)
                .filter(AudioAsset.song_id == song.id, AudioAsset.is_deleted.is_(False), AudioProject.is_deleted.is_(False))
                .order_by(AudioProject.id.desc())
                .first()
            )
        if project is None:
            project = AudioProject(title=song.title or asset.display_title or asset.title or "Unbenannt", cover_image_url=asset.image_url or song.cover_image_url)
            if asset.created_at:
                project.created_at = asset.created_at
            self.db.add(project)
            self.db.flush()
        asset.project_id = project.id
        if not song.project_id:
            song.project_id = project.id
            self.db.add(song)
        if not project.cover_image_url and (asset.image_url or song.cover_image_url):
            project.cover_image_url = asset.image_url or song.cover_image_url
            self.db.add(project)
        self.db.add(asset)
        return True

    def _sync_song_source_date(self, song: Song, candidates: list[AudioCandidate], *, dry_run: bool) -> bool:
        dates = [candidate.created_at for candidate in candidates if candidate.created_at]
        if not dates:
            source_dt = source_datetime_from_song(song)
            dates = [source_dt] if source_dt else []
        if not dates:
            return False
        # Für Song-/Projektgruppen ist der älteste Variantenzeitpunkt die
        # Erstellzeit des Generationspakets. Einzelvarianten sortieren trotzdem
        # über ihren eigenen AudioAsset-Zeitpunkt.
        source_dt = min(dates)
        metadata = dict(song.metadata_json or {}) if isinstance(song.metadata_json, dict) else {}
        changed = False
        if metadata.get("source_created_at") != source_dt.isoformat():
            metadata["source_created_at"] = source_dt.isoformat()
            changed = True
        if song.created_at and song.created_at != source_dt:
            changed = True
        if not changed:
            return False
        if dry_run:
            return True
        song.metadata_json = metadata
        if song.created_at != source_dt:
            song.created_at = source_dt
        self.db.add(song)
        return True
