from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AudioAsset, AudioProject, Song, SunoTask
from app.services.audio_asset_repair_service import is_bad_image_asset, is_audio_url, repair_local_file_metadata
from app.services.audio_cache_service import AudioCandidate, collect_audio_candidates
from app.utils.time_utils import utc_now_naive


SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}

OPERATION_LABELS = {
    "generate_music": "Generiert",
    "extend_music": "Extended",
    "upload_and_extend": "Extended",
    "upload_and_cover": "Cover Song",
    "add_vocals": "Add Vocals",
    "add_instrumental": "Add Instrumental",
    "generate_mashup": "Mashup",
    "generate_sounds": "Sound",
    "replace_section": "Replace Section",
    "separate": "Stem Separation",
    "convert_to_wav": "WAV",
    "generate_midi": "MIDI",
    "create_video": "Video",
    "imported_external": "Importiert",
}


@dataclass(slots=True)
class MaterializationResult:
    task_id: int | None
    suno_task_id: str | None
    task_type: str | None
    created: int = 0
    updated: int = 0
    skipped_deleted: int = 0
    recreated_deleted_matches: int = 0
    assets: list[AudioAsset] = field(default_factory=list)

    @property
    def asset_ids(self) -> list[int]:
        return [int(asset.id) for asset in self.assets if getattr(asset, "id", None)]

    @property
    def primary_asset(self) -> AudioAsset | None:
        return self.assets[0] if self.assets else None

    def as_payload(self) -> dict[str, Any]:
        return {
            "task_local_id": self.task_id,
            "suno_task_id": self.suno_task_id,
            "task_type": self.task_type,
            "created": self.created,
            "updated": self.updated,
            "skipped_deleted": self.skipped_deleted,
            "recreated_deleted_matches": self.recreated_deleted_matches,
            "audio_asset_ids": self.asset_ids,
            "primary_audio_asset_id": self.primary_asset.id if self.primary_asset else None,
        }


class AudioAssetMaterializationService:
    """Zentraler Root-Service für die fachliche Library-Materialisierung.

    Regel: Jeder erfolgreiche oder teil-erfolgreiche Audio-Task, der eine
    verwertbare Audio-URL liefert, muss idempotent mindestens ein AudioAsset
    erzeugen. Lokaler Download/Cache ist danach nur noch eine optionale
    Veredelung dieses Assets und darf nicht darüber entscheiden, ob die Library
    den Song kennt.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def materialize_task(
        self,
        task: SunoTask,
        *,
        song: Song | None = None,
        force: bool = False,
        commit: bool = True,
    ) -> MaterializationResult:
        result = MaterializationResult(
            task_id=getattr(task, "id", None),
            suno_task_id=getattr(task, "task_id", None),
            task_type=getattr(task, "task_type", None),
        )
        if not task:
            return result

        status = str(task.status or "").strip().upper()
        payload = {"response_payload": task.response_payload, "result_payload": task.result_payload}
        candidates = self._deduplicate_audio_candidates(collect_audio_candidates(payload))
        if not candidates:
            return result
        if not force and status not in SUCCESS_STATUSES:
            # Sobald Suno bereits verwertbare Audio-URLs liefert, darf FIRST_SUCCESS
            # materialisiert werden. Andere Zwischenzustände bleiben unberührt.
            return result

        resolved_song = song or self._find_or_create_song(task, candidates)
        created_asset_ids: set[int] = set()
        for candidate in candidates:
            before_id = self._active_match_id(candidate)
            deleted_match = before_id is None and self._has_deleted_match(candidate)
            asset, changed = self._upsert_candidate(task, candidate, resolved_song, recreated_from_deleted_match=deleted_match)
            if asset is None:
                continue
            if before_id is None:
                result.created += 1
                if deleted_match:
                    result.recreated_deleted_matches += 1
                if getattr(asset, "id", None):
                    created_asset_ids.add(int(asset.id))
            elif changed:
                result.updated += 1
            result.assets.append(asset)

        project_changes = self._assign_projects(result.assets, resolved_song, created_asset_ids=created_asset_ids)
        result.updated += project_changes
        task_metadata_changed = self._sync_task_materialization_metadata(task, result)

        if commit and (result.created or result.updated or result.skipped_deleted or task_metadata_changed):
            self.db.commit()
            for asset in result.assets:
                self.db.refresh(asset)
            if resolved_song is not None and getattr(resolved_song, "id", None):
                self.db.refresh(resolved_song)
            self.db.refresh(task)
        return result

    def materialize_recent_tasks(self, *, limit: int = 80, force: bool = True) -> MaterializationResult:
        aggregate = MaterializationResult(task_id=None, suno_task_id=None, task_type="aggregate")
        rows = (
            self.db.query(SunoTask)
            .filter(SunoTask.is_deleted.is_(False))
            .order_by(SunoTask.updated_at.desc(), SunoTask.id.desc())
            .limit(max(1, int(limit)))
            .all()
        )
        for task in rows:
            result = self.materialize_task(task, force=force, commit=False)
            aggregate.created += result.created
            aggregate.updated += result.updated
            aggregate.skipped_deleted += result.skipped_deleted
            aggregate.recreated_deleted_matches += result.recreated_deleted_matches
            aggregate.assets.extend(result.assets)
        if aggregate.created or aggregate.updated or aggregate.skipped_deleted:
            self.db.commit()
            for asset in aggregate.assets:
                self.db.refresh(asset)
        return aggregate


    @staticmethod
    def _deduplicate_audio_candidates(candidates: list[AudioCandidate]) -> list[AudioCandidate]:
        """Collapse duplicate SunoData variants from legacy payloads.

        Some task payloads contain the same audio URL twice: once as a proper
        Suno clip entry with id and once as a plain URL candidate. Materializing
        both causes false missing-asset findings. The source URL is the strongest
        identity here; when duplicated, keep the candidate carrying audio_id.
        """
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
            if not existing.audio_id and candidate.audio_id:
                by_source[source_key] = candidate
                by_audio_id.add(audio_key)
        return list(by_source.values())

    def _active_match_id(self, candidate: AudioCandidate) -> int | None:
        asset = self._find_active_asset(candidate)
        return int(asset.id) if asset is not None and getattr(asset, "id", None) else None

    def _find_active_asset(self, candidate: AudioCandidate) -> AudioAsset | None:
        if candidate.audio_id:
            matches = (
                self.db.query(AudioAsset)
                .filter(AudioAsset.audio_id == str(candidate.audio_id), AudioAsset.is_deleted.is_(False))
                .all()
            )
            matches = [item for item in matches if not is_bad_image_asset(item)]
            if matches:
                return sorted(matches, key=lambda item: (item.status == "cached", item.id or 0), reverse=True)[0]
        if candidate.source_url:
            return (
                self.db.query(AudioAsset)
                .filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(False))
                .order_by(AudioAsset.id.desc())
                .first()
            )
        return None

    def _has_deleted_match(self, candidate: AudioCandidate) -> bool:
        query = self.db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(True))
        if candidate.audio_id:
            if query.filter(AudioAsset.audio_id == str(candidate.audio_id)).first():
                return True
        if candidate.source_url:
            if self.db.query(AudioAsset).filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(True)).first():
                return True
        return False

    def _upsert_candidate(self, task: SunoTask, candidate: AudioCandidate, song: Song | None, *, recreated_from_deleted_match: bool = False) -> tuple[AudioAsset | None, bool]:
        if not candidate.source_url or not is_audio_url(candidate.source_url):
            return None, False

        asset = self._find_active_asset(candidate)

        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        operation_label = OPERATION_LABELS.get(str(task.task_type or ""), str(task.task_type or "Audio"))
        display_title = candidate.title or (song.title if song else None) or request_payload.get("title") or request_payload.get("name") or operation_label
        parent_audio_id = request_payload.get("audio_id") or request_payload.get("audioId") or self._metadata_value(candidate.metadata, "parentAudioId", "parent_audio_id")
        parent_task_id = request_payload.get("task_id") or request_payload.get("taskId") or self._metadata_value(candidate.metadata, "parentTaskId", "parent_task_id")

        metadata = {
            "candidate": candidate.metadata or {},
            "request_payload": request_payload,
            "operation": operation_label,
            "materialized_at": utc_now_naive().isoformat(),
            "materialized_by": "audio_asset_materialization_service",
        }
        if candidate.created_at:
            metadata["source_created_at"] = candidate.created_at.isoformat()
        if recreated_from_deleted_match:
            metadata["recreated_from_deleted_match"] = True

        if asset is None:
            asset = AudioAsset(
                task_local_id=task.id,
                song_id=song.id if song else None,
                suno_task_id=task.task_id,
                audio_id=str(candidate.audio_id) if candidate.audio_id else None,
                title=candidate.title,
                display_title=display_title,
                image_url=candidate.image_url,
                source_url=candidate.source_url,
                duration_seconds=candidate.duration_seconds,
                status="remote",
                operation_label=operation_label,
                parent_audio_id=str(parent_audio_id) if parent_audio_id else None,
                parent_task_id=str(parent_task_id) if parent_task_id else None,
                content_type="audio/mpeg" if str(candidate.source_url).lower().split("?", 1)[0].endswith(".mp3") else None,
                metadata_json=metadata,
            )
            if candidate.created_at:
                asset.created_at = candidate.created_at
                asset.updated_at = max(candidate.created_at, asset.updated_at or candidate.created_at)
            self.db.add(asset)
            self.db.flush()
            changed = True
        else:
            changed = False
            changed |= self._set_if_missing(asset, "task_local_id", task.id)
            changed |= self._set_if_missing(asset, "song_id", song.id if song else None)
            changed |= self._set_if_missing(asset, "suno_task_id", task.task_id)
            changed |= self._set_if_missing(asset, "audio_id", str(candidate.audio_id) if candidate.audio_id else None)
            changed |= self._set_if_missing(asset, "title", candidate.title)
            changed |= self._set_if_missing(asset, "display_title", display_title)
            changed |= self._set_if_missing(asset, "image_url", candidate.image_url)
            changed |= self._set_if_missing(asset, "duration_seconds", candidate.duration_seconds)
            changed |= self._set_if_missing(asset, "operation_label", operation_label)
            changed |= self._set_if_missing(asset, "parent_audio_id", str(parent_audio_id) if parent_audio_id else None)
            changed |= self._set_if_missing(asset, "parent_task_id", str(parent_task_id) if parent_task_id else None)
            if asset.source_url != candidate.source_url:
                asset.source_url = candidate.source_url
                changed = True
            if str(asset.status or "").lower() in {"", "created", "failed"} and not asset.local_path:
                asset.status = "remote"
                changed = True

            existing_meta = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
            new_meta = dict(existing_meta)
            if "candidate" not in new_meta and candidate.metadata:
                new_meta["candidate"] = candidate.metadata
            if "request_payload" not in new_meta and request_payload:
                new_meta["request_payload"] = request_payload
            if not new_meta.get("operation"):
                new_meta["operation"] = operation_label
            if not new_meta.get("materialized_by"):
                new_meta["materialized_by"] = "audio_asset_materialization_service"
            if candidate.created_at:
                new_meta.setdefault("source_created_at", candidate.created_at.isoformat())
                # Importierte Alt-Songs sollen nach SunoAPI.org-Erstelldatum sortieren.
                # Für lokale App-Änderungshistorie bleibt updated_at unverändert.
                if asset.created_at and asset.created_at > candidate.created_at:
                    asset.created_at = candidate.created_at
                    changed = True
            if new_meta != existing_meta:
                asset.metadata_json = new_meta
                changed = True
            if changed:
                self.db.add(asset)

        if repair_local_file_metadata(asset):
            changed = True
            self.db.add(asset)
        return asset, changed

    def _find_or_create_song(self, task: SunoTask, candidates: list[AudioCandidate]) -> Song | None:
        task_ids = [value for value in [task.task_id, self._parent_task_id(task)] if value]
        for task_id in task_ids:
            song = (
                self.db.query(Song)
                .filter(Song.task_id == str(task_id), Song.is_deleted.is_(False))
                .order_by(Song.id.desc())
                .first()
            )
            if song:
                return song

        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        title = request_payload.get("title") or request_payload.get("name") or next((item.title for item in candidates if item.title), None) or task.task_type
        source_created_at = next((item.created_at for item in candidates if item.created_at), None)
        if not any([title, task.task_id, candidates]):
            return None
        song = Song(
            title=str(title) if title else None,
            model=request_payload.get("model"),
            prompt=request_payload.get("prompt"),
            lyrics=request_payload.get("lyrics"),
            audio_url=candidates[0].source_url if candidates else None,
            cover_image_url=next((item.image_url for item in candidates if item.image_url), None),
            task_id=task.task_id,
            metadata_json={
                "request_payload": task.request_payload,
                "response_payload": task.response_payload,
                "result_payload": task.result_payload,
                "created_by": "audio_asset_materialization_service",
            },
        )
        if source_created_at:
            song.created_at = source_created_at
        self.db.add(song)
        self.db.flush()
        return song

    def _assign_projects(self, assets: list[AudioAsset], song: Song | None, *, created_asset_ids: set[int] | None = None) -> int:
        changed_existing_assets = 0
        created_asset_ids = created_asset_ids or set()
        for asset in assets:
            if asset.project_id:
                continue
            project = self._existing_project(asset, song)
            if project is None:
                project = AudioProject(
                    title=asset.display_title or asset.title or (song.title if song else None) or "Unbenannt",
                    cover_image_url=asset.image_url,
                )
                if getattr(asset, "created_at", None):
                    project.created_at = asset.created_at
                self.db.add(project)
                self.db.flush()
            asset.project_id = project.id
            if getattr(asset, "id", None) and int(asset.id) not in created_asset_ids:
                changed_existing_assets += 1
            if song and not song.project_id:
                song.project_id = project.id
                self.db.add(song)
            if not project.cover_image_url and asset.image_url:
                project.cover_image_url = asset.image_url
            self.db.add(asset)
        return changed_existing_assets

    def _existing_project(self, asset: AudioAsset, song: Song | None) -> AudioProject | None:
        project_ids: list[int] = []
        if song and song.project_id:
            project_ids.append(int(song.project_id))
        for field_name, value in (
            ("song_id", asset.song_id),
            ("suno_task_id", asset.suno_task_id),
            ("task_local_id", asset.task_local_id),
        ):
            if value is None:
                continue
            rows = (
                self.db.query(AudioAsset.project_id)
                .filter(getattr(AudioAsset, field_name) == value, AudioAsset.project_id.isnot(None), AudioAsset.is_deleted.is_(False))
                .all()
            )
            project_ids.extend(int(row.project_id) for row in rows if row.project_id is not None)
        for project_id in dict.fromkeys(project_ids):
            project = self.db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
            if project:
                return project
        return None

    def _sync_task_materialization_metadata(self, task: SunoTask, result: MaterializationResult) -> bool:
        metadata = dict(task.response_payload or {}) if isinstance(task.response_payload, dict) else {}
        existing = dict(metadata.get("materialized_audio_assets") or {}) if isinstance(metadata.get("materialized_audio_assets"), dict) else {}
        stable_payload = {
            "task_local_id": result.task_id,
            "suno_task_id": result.suno_task_id,
            "task_type": result.task_type,
            "audio_asset_ids": result.asset_ids,
            "primary_audio_asset_id": result.primary_asset.id if result.primary_asset else None,
            "skipped_deleted": result.skipped_deleted,
            "materialized_by": "audio_asset_materialization_service",
        }
        # Keine flüchtigen Zeitstempel oder Laufzähler speichern. Sonst würde
        # jeder reine Prüflauf wieder als "Metadaten repariert" erscheinen.
        if existing == stable_payload:
            return False
        metadata["materialized_audio_assets"] = stable_payload
        task.response_payload = metadata
        self.db.add(task)
        return True

    @staticmethod
    def _set_if_missing(asset: AudioAsset, field_name: str, value: Any) -> bool:
        if value is None:
            return False
        if not getattr(asset, field_name, None):
            setattr(asset, field_name, value)
            return True
        return False

    @staticmethod
    def _metadata_value(metadata: dict[str, Any] | None, *keys: str) -> Any:
        if not isinstance(metadata, dict):
            return None
        for key in keys:
            if metadata.get(key):
                return metadata.get(key)
        return None

    @staticmethod
    def _parent_task_id(task: SunoTask) -> str | None:
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        return request_payload.get("task_id") or request_payload.get("taskId")
