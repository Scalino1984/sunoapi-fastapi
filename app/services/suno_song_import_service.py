from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ActivityLog, AudioAsset, PlaylistItem, Song, StatusNotification, SunoTask
from app.services.asset_capabilities import local_only_capabilities, mark_suno_public_clip
from app.services.audio_cache_service import AudioCacheService, AudioCandidate, CoverCacheService, extract_source_created_at
from app.utils.time_utils import utc_now_naive


UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class SunoSongImportService:
    """Importiert einzelne öffentliche Suno-Clip-IDs in dieselbe App-Struktur wie generierte Songs."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    @staticmethod
    def extract_clip_id(value: str) -> str:
        text = str(value or "").strip()
        match = UUID_RE.search(text)
        if not match:
            raise ValueError("Keine gültige Suno Song-/Clip-ID gefunden. Erwartet wird eine UUID oder eine Suno-Song-URL mit UUID.")
        return match.group(0).lower()

    async def import_song(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.suno_clip_import_enabled:
            raise HTTPException(status_code=403, detail="Suno Song-ID Import ist serverseitig deaktiviert.")

        clip_id = self.extract_clip_id(str(payload.get("song_id") or ""))
        task_key = f"clip:{clip_id}"
        overwrite = bool(payload.get("overwrite_existing", False))
        cache_audio = bool(payload.get("cache_audio", True))
        cache_cover = bool(payload.get("cache_cover", True))
        import_video_url = bool(payload.get("import_video_url", True))
        project_id = payload.get("project_id")
        playlist_id = payload.get("playlist_id")

        existing = self._find_existing(clip_id, task_key)
        if existing and not overwrite:
            task, song, asset = existing
            self._notify_duplicate(task, song, asset, clip_id)
            return {
                "ok": True,
                "song_id": song.id if song else None,
                "audio_asset_id": asset.id if asset else None,
                "task_local_id": task.id if task else None,
                "suno_song_id": clip_id,
                "already_imported": True,
                "audio_cached": bool(asset and asset.status == "cached" and asset.public_url),
                "cover_cached": bool((asset and asset.cover_cached) or (song and song.cover_cached)),
                "message": "Suno-Clip war bereits importiert. Es wurde kein Duplikat erzeugt.",
                "warnings": [],
            }

        clip = await self._fetch_clip(clip_id)
        request_payload, response_payload, result_payload, candidate = self._build_payloads(clip, clip_id, task_key)

        warnings: list[str] = []
        task = self._upsert_task(task_key, request_payload, response_payload, result_payload, overwrite=overwrite)
        song = self._upsert_song(
            task,
            clip,
            request_payload,
            response_payload,
            result_payload,
            project_id=int(project_id) if project_id else None,
            import_video_url=import_video_url,
        )

        asset: AudioAsset | None = None
        if candidate.source_url:
            asset = self._upsert_asset(task, song, candidate, clip_id, request_payload, project_id=int(project_id) if project_id else None)
            if cache_audio:
                try:
                    asset = await AudioCacheService(self.db).cache_candidate(candidate, task=task, song=song)
                    asset.metadata_json = self._merge_asset_metadata(asset.metadata_json, clip, clip_id, request_payload)
                    asset.operation_label = asset.operation_label or "Suno Import"
                    self.db.add(asset)
                    self.db.commit()
                    self.db.refresh(asset)
                except Exception as exc:
                    warnings.append(f"Audio-Download fehlgeschlagen: {exc}")
                    asset.status = "failed"
                    asset.error_message = str(exc)
                    asset.metadata_json = self._merge_asset_metadata(asset.metadata_json, clip, clip_id, request_payload)
                    self.db.add(asset)
                    self.db.commit()
                    self.db.refresh(asset)
            else:
                asset.status = asset.status or "remote"
                asset.metadata_json = self._merge_asset_metadata(asset.metadata_json, clip, clip_id, request_payload)
                self.db.add(asset)
                self.db.commit()
                self.db.refresh(asset)

        cover_cached = False
        if cache_cover:
            try:
                cover = await CoverCacheService(self.db).cache_song_cover(song, image_url=self._clip_image_url(clip))
                cover_cached = bool(cover)
                if asset:
                    asset_cover = await CoverCacheService(self.db).cache_asset_cover(asset, image_url=self._clip_image_url(clip))
                    cover_cached = bool(asset_cover) or cover_cached
                    self.db.refresh(asset)
                self.db.refresh(song)
            except Exception as exc:
                warnings.append(f"Cover-Download fehlgeschlagen: {exc}")

        if playlist_id and asset:
            self._add_to_playlist(int(playlist_id), asset, song)

        task.status = "SUCCESS"
        task.error_message = " | ".join(warnings) if warnings else None
        task.updated_at = utc_now_naive()
        self.db.add(ActivityLog(
            action="suno_clip_import_completed",
            content_type="audio" if asset else "song",
            content_id=asset.id if asset else song.id,
            old_value=None,
            new_value={"task_id": task.task_id, "song_id": song.id, "audio_asset_id": asset.id if asset else None},
            metadata_json={"import_source": "suno_public_clip", "suno_clip_id": clip_id, "warnings": warnings},
        ))
        self._notify_success(task, song, asset, clip_id, warnings)
        self.db.commit()
        self.db.refresh(task)
        self.db.refresh(song)
        if asset:
            self.db.refresh(asset)

        return {
            "ok": True,
            "song_id": song.id,
            "audio_asset_id": asset.id if asset else None,
            "task_local_id": task.id,
            "suno_song_id": clip_id,
            "already_imported": False,
            "audio_cached": bool(asset and asset.status == "cached" and asset.public_url),
            "cover_cached": cover_cached or bool((asset and asset.cover_cached) or song.cover_cached),
            "message": "Öffentlicher Suno-Clip wurde in die Library importiert.",
            "warnings": warnings,
        }

    async def _fetch_clip(self, clip_id: str) -> dict[str, Any]:
        url = self.settings.suno_clip_api_url.format(id=clip_id)
        headers = {
            "User-Agent": self.settings.suno_clip_user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://suno.com/",
        }
        try:
            async with httpx.AsyncClient(timeout=float(self.settings.suno_clip_request_timeout_seconds), follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail=f"Suno Clip-API Timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Suno Clip-API Fehler: {exc}") from exc

        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Suno-Clip wurde nicht gefunden.")
        if response.status_code == 403:
            raise HTTPException(status_code=502, detail="Suno Clip-API blockiert den Abruf. User-Agent/Rate-Limit prüfen.")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Suno Clip-API lieferte HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Suno Clip-API lieferte kein gültiges JSON.") from exc
        if not isinstance(data, dict) or not data.get("id"):
            raise HTTPException(status_code=502, detail="Suno Clip-API Antwort enthält keine Clip-ID.")
        return data

    def _find_existing(self, clip_id: str, task_key: str) -> tuple[SunoTask | None, Song | None, AudioAsset | None] | None:
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_key, SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.desc()).first()
        song = self.db.query(Song).filter(Song.task_id == task_key, Song.is_deleted.is_(False)).order_by(Song.id.desc()).first()
        asset = self.db.query(AudioAsset).filter(AudioAsset.suno_task_id == task_key, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        if not asset:
            asset = self.db.query(AudioAsset).filter(AudioAsset.audio_id == clip_id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        if not task and not song and not asset:
            return None
        if not task:
            task = SunoTask(
                task_id=task_key,
                task_type="import_suno_song",
                status="IMPORTED_ALREADY_EXISTS",
                request_payload={"import_source": "suno_public_clip", "is_suno_clip_import": True, "suno_clip_id": clip_id, "duplicate_detected": True},
                response_payload={"source": "suno_clip_import", "taskId": task_key, "duplicate_detected": True},
            )
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)
        if not song and asset and asset.song_id:
            song = self.db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if not asset and song:
            asset = self.db.query(AudioAsset).filter(AudioAsset.song_id == song.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        return task, song, asset

    def _build_payloads(self, clip: dict[str, Any], clip_id: str, task_key: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], AudioCandidate]:
        metadata = clip.get("metadata") if isinstance(clip.get("metadata"), dict) else {}
        lyrics = str(metadata.get("prompt") or clip.get("prompt") or "").strip() or None
        style = str(metadata.get("tags") or clip.get("tags") or "").strip() or None
        title = str(clip.get("title") or clip_id).strip()
        model = str(clip.get("major_model_version") or metadata.get("model") or clip.get("model_name") or "suno").strip()
        audio_url = str(clip.get("audio_url") or clip.get("audioUrl") or "").strip()
        image_url = self._clip_image_url(clip)
        duration = self._duration_seconds(metadata.get("duration") or clip.get("duration"))
        source_created_at = extract_source_created_at(clip)
        capabilities = local_only_capabilities()
        request_payload = {
            "source": "suno_clip_import",
            "import_source": "suno_public_clip",
            "is_suno_clip_import": True,
            "suno_clip_id": clip_id,
            "task_id": task_key,
            "audio_id": clip_id,
            "title": title,
            "prompt": lyrics,
            "lyrics": lyrics,
            "style": style,
            "model": model,
            "source_url": audio_url or None,
            "source_created_at": source_created_at.isoformat() if source_created_at else None,
            "capabilities": capabilities,
        }
        if metadata.get("negative_tags"):
            request_payload["negative_tags"] = metadata.get("negative_tags")
        sliders = metadata.get("control_sliders") if isinstance(metadata.get("control_sliders"), dict) else {}
        if sliders.get("style_weight") is not None:
            request_payload["styleWeight"] = sliders.get("style_weight")
        if sliders.get("weirdness_constraint") is not None:
            request_payload["weirdnessConstraint"] = sliders.get("weirdness_constraint")

        candidate_dict = {
            "id": clip_id,
            "audioId": clip_id,
            "audio_id": clip_id,
            "title": title,
            "prompt": lyrics,
            "lyrics": lyrics,
            "text": lyrics,
            "tags": style,
            "style": style,
            "modelName": model,
            "model": model,
            "audioUrl": audio_url,
            "sourceAudioUrl": audio_url,
            "imageUrl": image_url,
            "sourceImageUrl": image_url,
            "duration": duration,
            "created_at": source_created_at.isoformat() if source_created_at else None,
            "import_source": "suno_public_clip",
            "is_suno_clip_import": True,
            "capabilities": capabilities,
        }
        result_payload = {
            "source": "suno_clip_import",
            "import_source": "suno_public_clip",
            "is_suno_clip_import": True,
            "status": "SUCCESS",
            "taskId": task_key,
            "sunoData": [candidate_dict],
            "clip": clip,
            "capabilities": capabilities,
        }
        response_payload = {"source": "suno_clip_import", "taskId": task_key, "suno_clip_id": clip_id, "capabilities": capabilities}
        candidate = AudioCandidate(source_url=audio_url, audio_id=clip_id, title=title, image_url=image_url, duration_seconds=duration, created_at=source_created_at, metadata=candidate_dict)
        return request_payload, response_payload, result_payload, candidate

    def _upsert_task(self, task_key: str, request_payload: dict[str, Any], response_payload: dict[str, Any], result_payload: dict[str, Any], *, overwrite: bool) -> SunoTask:
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_key, SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.desc()).first()
        if not task:
            task = SunoTask(task_id=task_key, task_type="import_suno_song")
            source_created_at = extract_source_created_at(request_payload)
            if source_created_at:
                task.created_at = source_created_at
            self.db.add(task)
        task.status = "SUCCESS"
        task.request_payload = request_payload
        task.response_payload = response_payload
        task.result_payload = result_payload
        task.error_message = None
        task.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(task)
        return task

    def _upsert_song(self, task: SunoTask, clip: dict[str, Any], request_payload: dict[str, Any], response_payload: dict[str, Any], result_payload: dict[str, Any], *, project_id: int | None, import_video_url: bool) -> Song:
        song = self.db.query(Song).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).order_by(Song.id.desc()).first()
        if not song:
            song = Song(task_id=task.task_id)
            source_created_at = extract_source_created_at(request_payload)
            if source_created_at:
                song.created_at = source_created_at
            self.db.add(song)
        title = request_payload.get("title") or request_payload.get("suno_clip_id")
        lyrics = request_payload.get("lyrics") or request_payload.get("prompt")
        image_url = self._clip_image_url(clip)
        song.title = title
        song.model = request_payload.get("model")
        song.prompt = lyrics
        song.lyrics = lyrics
        song.audio_url = request_payload.get("source_url")
        song.cover_image_url = image_url or song.cover_image_url
        song.video_url = (clip.get("video_url") or clip.get("videoUrl") or song.video_url) if import_video_url else song.video_url
        if project_id:
            song.project_id = project_id
        compact_info = {
            "id": request_payload.get("suno_clip_id"),
            "title": title,
            "style": request_payload.get("style"),
            "model": request_payload.get("model"),
            "audio_url": request_payload.get("source_url"),
            "image_url": image_url,
            "video_url": clip.get("video_url") or clip.get("videoUrl"),
        }
        metadata = {
            "clip": clip,
            "info": compact_info,
            "request_payload": request_payload,
            "response_payload": response_payload,
            "result_payload": result_payload,
            "source_image_url": image_url,
        }
        song.metadata_json = mark_suno_public_clip(metadata, suno_clip_id=str(request_payload.get("suno_clip_id")))
        self.db.commit()
        self.db.refresh(song)
        return song

    def _upsert_asset(self, task: SunoTask, song: Song, candidate: AudioCandidate, clip_id: str, request_payload: dict[str, Any], *, project_id: int | None) -> AudioAsset:
        asset = self.db.query(AudioAsset).filter(AudioAsset.suno_task_id == task.task_id, AudioAsset.audio_id == clip_id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        if not asset:
            asset = self.db.query(AudioAsset).filter(AudioAsset.source_url == candidate.source_url, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
        if not asset:
            asset = AudioAsset(source_url=candidate.source_url, status="created")
            if candidate.created_at:
                asset.created_at = candidate.created_at
            self.db.add(asset)
        asset.task_local_id = task.id
        asset.song_id = song.id
        asset.suno_task_id = task.task_id
        asset.audio_id = clip_id
        asset.title = candidate.title
        asset.display_title = candidate.title
        asset.image_url = candidate.image_url
        asset.duration_seconds = candidate.duration_seconds
        asset.project_id = project_id or song.project_id
        asset.operation_label = "Suno Import"
        asset.version_label = "Suno Import"
        asset.metadata_json = self._merge_asset_metadata(asset.metadata_json, task.result_payload.get("clip") if isinstance(task.result_payload, dict) else {}, clip_id, request_payload)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def _merge_asset_metadata(self, metadata: dict[str, Any] | None, clip: dict[str, Any], clip_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(metadata or {})
        candidate = dict(merged.get("candidate") if isinstance(merged.get("candidate"), dict) else {})
        candidate.update((request_payload and {
            "id": clip_id,
            "audioId": clip_id,
            "audio_id": clip_id,
            "title": request_payload.get("title"),
            "prompt": request_payload.get("prompt"),
            "lyrics": request_payload.get("lyrics"),
            "text": request_payload.get("lyrics"),
            "tags": request_payload.get("style"),
            "style": request_payload.get("style"),
            "modelName": request_payload.get("model"),
            "model": request_payload.get("model"),
            "audioUrl": request_payload.get("source_url"),
            "sourceAudioUrl": request_payload.get("source_url"),
            "imageUrl": self._clip_image_url(clip),
            "sourceImageUrl": self._clip_image_url(clip),
            "created_at": request_payload.get("source_created_at"),
        }) or {})
        merged.update({
            "candidate": candidate,
            "request_payload": request_payload,
            "operation": "Suno Import",
            "clip": clip,
            "source_created_at": request_payload.get("source_created_at"),
        })
        return mark_suno_public_clip(merged, suno_clip_id=clip_id)

    def _add_to_playlist(self, playlist_id: int, asset: AudioAsset, song: Song) -> None:
        existing = self.db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id, PlaylistItem.audio_asset_id == asset.id).first()
        if existing:
            return
        max_position = max((row.position for row in self.db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id).all()), default=0)
        self.db.add(PlaylistItem(playlist_id=playlist_id, audio_asset_id=asset.id, song_id=song.id, position=max_position + 1, note="Suno Clip Import"))

    def _notify_duplicate(self, task: SunoTask | None, song: Song | None, asset: AudioAsset | None, clip_id: str) -> None:
        self.db.add(StatusNotification(
            event_type="suno_clip_import_duplicate",
            title="Suno-Clip bereits vorhanden",
            message=f"Clip {clip_id} wurde nicht doppelt importiert.",
            severity="info",
            status="unread",
            task_local_id=task.id if task else None,
            suno_task_id=task.task_id if task else f"clip:{clip_id}",
            content_type="audio" if asset else "song" if song else "task",
            content_id=asset.id if asset else song.id if song else task.id if task else None,
            target_tab="library",
            target_payload={"suno_clip_id": clip_id, "already_imported": True, "audio_asset_id": asset.id if asset else None, "song_id": song.id if song else None},
        ))
        self.db.commit()

    def _notify_success(self, task: SunoTask, song: Song, asset: AudioAsset | None, clip_id: str, warnings: list[str]) -> None:
        self.db.add(StatusNotification(
            event_type="suno_clip_import_completed",
            title=f"Suno-Clip importiert: {song.title or clip_id}",
            message=("; ".join(warnings) if warnings else "Song wurde in die Library übernommen."),
            severity="warning" if warnings else "success",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="audio" if asset else "song",
            content_id=asset.id if asset else song.id,
            target_tab="library",
            target_payload={"suno_clip_id": clip_id, "task_local_id": task.id, "song_id": song.id, "audio_asset_id": asset.id if asset else None, "status": "SUCCESS"},
        ))

    @staticmethod
    def _clip_image_url(clip: dict[str, Any]) -> str | None:
        return clip.get("image_large_url") or clip.get("image_url") or clip.get("imageUrl") or clip.get("cover_url")

    @staticmethod
    def _duration_seconds(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None
