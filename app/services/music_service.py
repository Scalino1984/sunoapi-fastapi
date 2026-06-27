"""Suno task orchestration and local library materialization.

Generate-/Extend-Music-Vertrag: die offiziellen SunoAPI-Optionen negativeTags,
vocalGender, styleWeight, weirdnessConstraint, audioWeight sowie Extend-Felder
audioId, continueAt und defaultParamFlag muessen bis zum SunoAPI-Call und bis
suno_tasks.request_payload erhalten bleiben. Von dort werden sie bei der
AudioAsset-Materialisierung fuer Songdetails/Library/Offline-Anzeige in
metadata_json.request_payload gespiegelt.

Bestandsreparatur-Vertrag fuer importierte SunoAPI.org-Tasks:
record-info liefert die urspruenglichen Request-Optionen haeufig nicht als
Objekt, sondern als JSON-String in data.param. Diese Struktur muss beim
Provider-Backfill geparst werden, damit "Inhalte pruefen" bereits importierte
Songs nachtraeglich mit Verwendete Optionen reparieren kann. Den
generation_options_provider_check_version-Marker nur erhoehen, wenn die
Extraktionslogik absichtlich erweitert wurde; sonst werden alte Tasks
unnoetig erneut gegen SunoAPI abgefragt.
"""

from __future__ import annotations

import json
from typing import Any
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.models import AudioAsset, Persona, Song, StatusNotification, SunoTask
from app.services.audio_cache_service import AudioCacheService, CoverCacheService, collect_audio_candidates, collect_image_urls, extract_source_created_at
from app.services.audio_asset_materialization_service import AudioAssetMaterializationService
from app.services.song_library_sync_service import song_sort_datetime
from app.suno_client import SunoAPIClient
from app.utils.time_utils import utc_now_naive


TASK_ID_KEYS = ("task_id", "taskId", "id")
STATUS_KEYS = ("status", "state", "msg")
LYRICS_KEYS = ("lyrics", "lyric", "songtext", "text", "content")
TITLE_KEYS = ("title", "name", "songTitle", "displayName")

LOCAL_APP_TASK_TYPES = {
    "generate_srt",
    "generate_stems",
    "bulk_generate_srt",
    "bulk_generate_stems",
    "generate_cover_art",
    "library_ai_tagging",
    "bulk_library_ai_tagging",
    "convert_to_wav_local",
    "import_suno_song",
    "import_suno_song_batch",
    "import_sunoapi_task_batch",
}

IMPORT_DEDUP_BLOCKING_ACTIVE_STATUSES = {
    "SUBMITTED",
    "PENDING",
    "PROCESSING",
    "RUNNING",
    "QUEUED",
    "CREATED",
    "CANCEL_REQUESTED",
}

URL_KEYS = (
    "audio_url",
    "audioUrl",
    "source_audio_url",
    "sourceAudioUrl",
    "video_url",
    "videoUrl",
    "midi_url",
    "midiUrl",
    "wav_url",
    "wavUrl",
)

ADVANCED_GENERATION_OPTION_ALIASES = {
    "negativeTags": ("negativeTags", "negative_tags", "negativePrompt", "negative_prompt"),
    "vocalGender": ("vocalGender", "vocal_gender", "voiceGender", "voice_gender", "gender"),
    "styleWeight": ("styleWeight", "style_weight", "styleStrength", "style_strength"),
    "weirdnessConstraint": ("weirdnessConstraint", "weirdness_constraint", "weirdness", "weirdnessWeight", "weirdness_weight"),
    "audioWeight": ("audioWeight", "audio_weight", "audioStrength", "audio_strength"),
    "customMode": ("customMode", "custom_mode"),
    "instrumental": ("instrumental", "makeInstrumental", "make_instrumental"),
    "personaId": ("personaId", "persona_id", "voiceId", "voice_id"),
    "personaModel": ("personaModel", "persona_model"),
}

IMPORTED_GENERATION_OPTION_KEYS = (
    "styleWeight",
    "vocalGender",
    "weirdnessConstraint",
    "audioWeight",
    "negativeTags",
    "customMode",
    "instrumental",
    "personaId",
    "personaModel",
)
GENERATION_OPTIONS_PROVIDER_CHECK_VERSION = "sunoapi-options-v3"


def _walk_values(payload: Any):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _walk_values(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_values(value)


def _walk_values_with_json_strings(payload: Any):
    if isinstance(payload, dict):
        yield payload
        values = payload.values()
    elif isinstance(payload, list):
        values = payload
    else:
        return
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if not text or text[0] not in "{[" or len(text) > 500_000:
                continue
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            if isinstance(parsed, (dict, list)):
                yield from _walk_values_with_json_strings(parsed)
        elif isinstance(value, (dict, list)):
            yield from _walk_values_with_json_strings(value)


def _extract_task_id(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in TASK_ID_KEYS:
            value = item.get(key)
            if value:
                return str(value)
    return None


def _extract_parent_task_id(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in ("parentTaskId", "parent_task_id", "parentMusicId", "parent_music_id"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _extract_audio_id(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in ("audioId", "audio_id", "id"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _extract_voice_id(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in ("voiceId", "voice_id", "id"):
            value = item.get(key)
            if value:
                return str(value)
    return None


def _is_present_generation_option(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _extract_imported_generation_options(payload: Any) -> dict[str, Any]:
    """Extract official SunoAPI generation options from imported task details.

    Manual SunoAPI.org task imports receive the original request details from
    the provider, not from the local /music form. These options must be copied
    into suno_tasks.request_payload so AudioAsset materialization and offline
    Library/Songdetails can show "Verwendete Optionen" without remote lookups.
    """
    options: dict[str, Any] = {}
    for item in _walk_values_with_json_strings(payload):
        if not isinstance(item, dict):
            continue
        for canonical_key, aliases in ADVANCED_GENERATION_OPTION_ALIASES.items():
            if canonical_key in options:
                continue
            for alias in aliases:
                value = item.get(alias)
                if _is_present_generation_option(value):
                    options[canonical_key] = value.strip() if isinstance(value, str) else value
                    break
    return options


def _merge_generation_options_into_request(request_payload: dict[str, Any], *sources: Any) -> dict[str, Any]:
    merged = dict(request_payload or {})
    for source in sources:
        for key, value in _extract_imported_generation_options(source).items():
            if not _is_present_generation_option(merged.get(key)):
                merged[key] = value
    if _is_present_generation_option(merged.get("negative_tags")) and not _is_present_generation_option(merged.get("negativeTags")):
        merged["negativeTags"] = merged["negative_tags"]
    if _is_present_generation_option(merged.get("vocal_gender")) and not _is_present_generation_option(merged.get("vocalGender")):
        merged["vocalGender"] = merged["vocal_gender"]
    if _is_present_generation_option(merged.get("persona_id")) and not _is_present_generation_option(merged.get("personaId")):
        merged["personaId"] = merged["persona_id"]
    if _is_present_generation_option(merged.get("persona_model")) and not _is_present_generation_option(merged.get("personaModel")):
        merged["personaModel"] = merged["persona_model"]
    if _is_present_generation_option(merged.get("personaId")) and not _is_present_generation_option(merged.get("persona_id")):
        merged["persona_id"] = merged["personaId"]
    if _is_present_generation_option(merged.get("personaModel")) and not _is_present_generation_option(merged.get("persona_model")):
        merged["persona_model"] = merged["personaModel"]
    return merged


def _missing_imported_generation_option_keys(request_payload: dict[str, Any]) -> list[str]:
    return [key for key in IMPORTED_GENERATION_OPTION_KEYS if not _is_present_generation_option(request_payload.get(key))]


def _extract_status(payload: Any) -> str | None:
    for preferred_key in ("status", "state", "msg"):
        for item in _walk_values(payload):
            if not isinstance(item, dict):
                continue
            value = item.get(preferred_key)
            if value:
                return str(value)
    return None


def _extract_title(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in TITLE_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_first_text(payload: Any) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in LYRICS_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip() and len(value.strip()) >= 20:
                return value.strip()
    return None


def _extract_url(payload: Any, keys: tuple[str, ...]) -> str | None:
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return None


class MusicService:
    def __init__(self, db: Session, client: SunoAPIClient | None = None) -> None:
        self.db = db
        self.client = client or SunoAPIClient()
        self.settings = get_settings()

    def _with_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "callback_url" not in payload and "callBackUrl" not in payload:
            payload["callback_url"] = self.settings.callback_url

        voice_id = str(payload.get("voice_id") or payload.get("voiceId") or "").strip()
        if voice_id:
            payload.setdefault("persona_id", voice_id)
            payload.setdefault("persona_model", "voice_persona")

        if (payload.get("persona_id") or payload.get("personaId")) and not (payload.get("persona_model") or payload.get("personaModel")):
            payload["persona_model"] = "style_persona"

        return payload

    def _upsert_persona_from_payload(
        self,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> Persona | None:
        source = response_payload.get("data") if isinstance(response_payload, dict) else response_payload
        if not isinstance(source, dict):
            return None

        persona_id = source.get("personaId") or source.get("persona_id")
        if not persona_id:
            return None

        persona = (
            self.db.query(Persona)
            .filter(Persona.persona_id == str(persona_id), Persona.is_deleted.is_(False))
            .first()
        )

        if persona is None:
            persona = Persona(
                persona_id=str(persona_id),
                name=str(source.get("name") or request_payload.get("name") or persona_id),
            )
            self.db.add(persona)

        persona.name = str(source.get("name") or request_payload.get("name") or persona.name)
        persona.description = source.get("description") or request_payload.get("description")
        persona.style = source.get("style") or request_payload.get("style")
        persona.source_task_id = request_payload.get("task_id") or request_payload.get("taskId")
        persona.source_audio_id = request_payload.get("audio_id") or request_payload.get("audioId")
        persona.vocal_start = request_payload.get("vocalStart")
        persona.vocal_end = request_payload.get("vocalEnd")
        persona.response_payload = response_payload

        self.db.commit()
        self.db.refresh(persona)

        return persona

    def _upsert_voice_from_payload(
        self,
        request_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None,
    ) -> Persona | None:
        source = response_payload or {}
        voice_id = _extract_voice_id(source)
        if not voice_id:
            return None

        request_payload = request_payload or {}
        metadata = source.get("data") if isinstance(source, dict) and isinstance(source.get("data"), dict) else source
        voice_name = (
            request_payload.get("voice_name")
            or request_payload.get("voiceName")
            or request_payload.get("voiceName")
            or (metadata.get("voiceName") if isinstance(metadata, dict) else None)
            or (metadata.get("voice_name") if isinstance(metadata, dict) else None)
            or f"Voice {voice_id[:10]}"
        )

        persona = self.db.query(Persona).filter(Persona.persona_id == voice_id).first()
        if persona is None:
            persona = Persona(persona_id=voice_id, name=str(voice_name))
            self.db.add(persona)

        persona.name = str(voice_name)
        persona.description = request_payload.get("description") or getattr(persona, "description", None)
        persona.style = request_payload.get("style") or getattr(persona, "style", None)
        persona.source_task_id = (
            request_payload.get("task_id")
            or request_payload.get("taskId")
            or (metadata.get("taskId") if isinstance(metadata, dict) else None)
            or (metadata.get("task_id") if isinstance(metadata, dict) else None)
        )
        persona.response_payload = {
            "kind": "voice",
            "source_type": "voice",
            "voice_id": voice_id,
            "task_id": persona.source_task_id,
            "nickname": persona.name,
            "description": persona.description,
            "style": persona.style,
            "raw_response": response_payload,
        }
        self.db.commit()
        self.db.refresh(persona)
        return persona


    def list_personas(self, limit: int = 100) -> list[Persona]:
        return (
            self.db.query(Persona)
            .filter(Persona.is_deleted.is_(False))
            .order_by(Persona.created_at.desc())
            .limit(limit)
            .all()
        )

    def _voice_to_dict(self, persona: Persona) -> dict[str, Any]:
        metadata = persona.response_payload if isinstance(persona.response_payload, dict) else {}
        source_type = str(metadata.get("source_type") or metadata.get("kind") or "persona").strip().lower()
        if source_type not in {"voice", "persona"}:
            source_type = "persona"

        return {
            "id": persona.id,
            "voice_id": str(metadata.get("voice_id") or persona.persona_id),
            "nickname": persona.name,
            "task_id": metadata.get("task_id") or persona.source_task_id,
            "description": persona.description,
            "style": persona.style,
            "source_type": source_type,
            "response_payload": persona.response_payload,
            "created_at": persona.created_at,
            "updated_at": persona.updated_at,
        }

    def list_voices(self, limit: int = 200) -> list[dict[str, Any]]:
        personas = (
            self.db.query(Persona)
            .filter(Persona.is_deleted.is_(False))
            .order_by(Persona.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._voice_to_dict(persona) for persona in personas]

    def create_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        voice_id = str(payload.get("voice_id") or "").strip()
        nickname = str(payload.get("nickname") or "").strip()
        task_id = str(payload.get("task_id") or "").strip() or None
        description = payload.get("description")
        style = payload.get("style")

        if not voice_id:
            raise ValueError("voice_id fehlt.")
        if not nickname:
            raise ValueError("Spitzname fehlt.")

        persona = self.db.query(Persona).filter(Persona.persona_id == voice_id).first()
        if persona is None:
            persona = Persona(persona_id=voice_id, name=nickname)
            self.db.add(persona)

        persona.name = nickname
        persona.description = description
        persona.style = style
        persona.source_task_id = task_id or voice_id
        persona.is_deleted = False
        persona.deleted_at = None
        persona.deleted_reason = None
        persona.response_payload = {
            "kind": "voice",
            "source_type": "voice",
            "voice_id": voice_id,
            "task_id": task_id or voice_id,
            "nickname": nickname,
            "description": description,
            "style": style,
        }

        self.db.commit()
        self.db.refresh(persona)
        return self._voice_to_dict(persona)

    def update_voice(self, local_voice_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        persona = (
            self.db.query(Persona)
            .filter(Persona.id == local_voice_id, Persona.is_deleted.is_(False))
            .first()
        )
        if persona is None:
            raise ValueError("Voice wurde nicht gefunden.")

        metadata = persona.response_payload if isinstance(persona.response_payload, dict) else {}

        if payload.get("nickname") is not None:
            nickname = str(payload.get("nickname") or "").strip()
            if not nickname:
                raise ValueError("Spitzname darf nicht leer sein.")
            persona.name = nickname
            metadata["nickname"] = nickname

        if payload.get("voice_id") is not None:
            voice_id = str(payload.get("voice_id") or "").strip()
            if not voice_id:
                raise ValueError("Voice-ID darf nicht leer sein.")
            existing = self.db.query(Persona).filter(Persona.persona_id == voice_id, Persona.id != persona.id).first()
            if existing is not None:
                raise ValueError("Diese Voice-ID ist bereits vorhanden.")
            persona.persona_id = voice_id
            metadata["voice_id"] = voice_id

        if "task_id" in payload:
            task_id = str(payload.get("task_id") or "").strip() or None
            persona.source_task_id = task_id
            metadata["task_id"] = task_id

        if "description" in payload:
            persona.description = payload.get("description")
            metadata["description"] = payload.get("description")

        if "style" in payload:
            persona.style = payload.get("style")
            metadata["style"] = payload.get("style")

        metadata["kind"] = metadata.get("kind") or "voice"
        metadata["source_type"] = metadata.get("source_type") or "voice"
        persona.response_payload = metadata

        self.db.commit()
        self.db.refresh(persona)
        return self._voice_to_dict(persona)

    def delete_voice(self, local_voice_id: int) -> dict[str, Any]:
        persona = (
            self.db.query(Persona)
            .filter(Persona.id == local_voice_id, Persona.is_deleted.is_(False))
            .first()
        )
        if persona is None:
            raise ValueError("Voice wurde nicht gefunden.")

        persona.is_deleted = True
        persona.deleted_at = utc_now_naive()
        persona.deleted_reason = "Voice/Persona aus React-Verwaltung entfernt"
        self.db.commit()
        return {"ok": True, "deleted_voice_id": local_voice_id}

    def _store_task(
        self,
        task_type: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> SunoTask:
        extracted_task_id = _extract_task_id(response_payload)
        initial_status = "completed" if task_type in {"generate_persona", "boost_music_style"} and not extracted_task_id else "submitted"

        now = utc_now_naive()
        task = SunoTask(
            task_id=extracted_task_id,
            task_type=task_type,
            status=initial_status,
            request_payload=request_payload,
            response_payload=response_payload,
            started_at=now,
            heartbeat_at=now,
            completed_at=now if str(initial_status).lower() == "completed" else None,
            cancel_requested=False,
        )

        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        return task

    def _upsert_song_from_task(self, task: SunoTask) -> Song | None:
        source = task.result_payload or task.response_payload or {}
        request_payload = task.request_payload or {}
        source_created_at = extract_source_created_at(source)

        lyrics = _extract_first_text(source)
        audio_url = _extract_url(
            source,
            (
                "audio_url",
                "audioUrl",
                "source_audio_url",
                "sourceAudioUrl",
                "streamAudioUrl",
                "stream_audio_url",
            ),
        )
        video_url = _extract_url(source, ("video_url", "videoUrl", "mp4_url", "mp4Url"))
        midi_url = _extract_url(source, ("midi_url", "midiUrl"))
        wav_url = _extract_url(source, ("wav_url", "wavUrl"))
        image_urls = collect_image_urls(source)
        cover_image_url = image_urls[0] if image_urls else None

        if not any([lyrics, audio_url, video_url, midi_url, wav_url, cover_image_url]):
            return None

        parent_task_id = _extract_parent_task_id(source) or request_payload.get("task_id") or request_payload.get("taskId")

        song = None

        if task.task_type == "create_cover" and parent_task_id:
            song = self.db.query(Song).filter(Song.task_id == str(parent_task_id)).first()

        if song is None and task.task_id:
            song = self.db.query(Song).filter(Song.task_id == task.task_id).first()

        if song is None:
            song = Song(
                task_id=str(parent_task_id)
                if task.task_type == "create_cover" and parent_task_id
                else task.task_id
            )
            if source_created_at:
                song.created_at = source_created_at
            self.db.add(song)

        song.title = song.title or request_payload.get("title") or request_payload.get("name") or _extract_title(source) or task.task_type
        song.model = song.model or request_payload.get("model")
        song.prompt = song.prompt or request_payload.get("prompt")
        song.lyrics = lyrics or song.lyrics
        song.audio_url = audio_url or song.audio_url
        song.cover_image_url = cover_image_url or song.cover_image_url
        song.video_url = video_url or song.video_url
        song.midi_url = midi_url or song.midi_url
        song.wav_url = wav_url or song.wav_url
        if source_created_at and song.created_at and song.created_at > source_created_at:
            song.created_at = source_created_at

        song.metadata_json = {
            "request_payload": request_payload,
            "response_payload": task.response_payload,
            "result_payload": task.result_payload,
        }

        self.db.commit()
        self.db.refresh(song)

        return song

    async def _cache_audio_if_configured(self, task: SunoTask, song: Song | None = None) -> list[AudioAsset]:
        media_errors: list[str] = []
        materialized_assets: list[AudioAsset] = []

        # ROOT-REGEL:
        # AudioAssets sind die zentrale Library-Wahrheit und müssen sofort beim
        # erfolgreichen Task-Ergebnis entstehen. Der lokale Audio-Cache ist nur
        # eine optionale Veredelung. Ohne diese Entkopplung sieht die Statusseite
        # SUCCESS, während Library/Player/SRT/Stems noch keine Variante kennen.
        try:
            materialized = AudioAssetMaterializationService(self.db).materialize_task(task, song=song, force=True)
            materialized_assets = materialized.assets
        except Exception as exc:
            media_errors.append(f"AudioAsset-Materialisierung fehlgeschlagen: {exc}")

        # Covers werden unabhängig vom Audio-Download lokal gesichert,
        # weil externe Suno-Bildlinks nach einiger Zeit ablaufen können.
        try:
            await CoverCacheService(self.db).cache_task_covers(task, song=song)
        except Exception as exc:
            media_errors.append(f"Cover-Cache-Fehler: {exc}")

        try:
            cached_assets = await AudioCacheService(self.db).cache_task_audio(task, song=song)
            if cached_assets:
                materialized_assets = cached_assets
        except Exception as exc:
            media_errors.append(f"Audio-Cache-Fehler: {exc}")

        # Nach dem Audio-Cache nochmal Cover sichern, weil AudioAssets jetzt sicher existieren.
        try:
            await CoverCacheService(self.db).cache_task_covers(task, song=song)
        except Exception as exc:
            media_errors.append(f"Cover-Cache-Fehler nach Audio-Cache: {exc}")

        if media_errors:
            # Fehler beim optionalen Cache dürfen den Task nicht zurück auf FAILED setzen
            # und dürfen Remote-Assets nicht aus der Library verschwinden lassen.
            task.error_message = " | ".join(media_errors)
            self.db.commit()

        return materialized_assets

    @staticmethod
    def _clean_generate_payload_for_suno(payload: dict[str, Any]) -> dict[str, Any]:
        """Send only the fields that belong to the plain SunoAPI music generation request.

        The React page keeps a lot of workflow state around. Only real SunoAPI generate
        fields may pass this boundary. The advanced generate options below are part of
        the /music form, schema, DB display contract and Suno request contract; do not
        remove them from this allowlist or they disappear from both SunoAPI requests and
        suno_tasks.request_payload.
        """
        allowed = {
            "model",
            "customMode",
            "custom_mode",
            "instrumental",
            "prompt",
            "title",
            "style",
            "negative_tags",
            "negativeTags",
            "vocal_gender",
            "vocalGender",
            "styleWeight",
            "weirdnessConstraint",
            "audioWeight",
            "persona_id",
            "personaId",
            "persona_model",
            "personaModel",
            "callback_url",
            "call_back_url",
            "callBackUrl",
        }
        cleaned: dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if key not in allowed:
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            cleaned[key] = value
        return cleaned

    async def generate_music(self, payload: dict[str, Any]) -> SunoTask:
        request_payload = self._with_callback(self._clean_generate_payload_for_suno(payload))
        response_payload = await self.client.generate_music(request_payload)
        task = self._store_task("generate_music", request_payload, response_payload)
        self._create_task_started_notification(task, request_payload.get("title"))

        song = Song(
            title=request_payload.get("title") or "Musikgenerierung",
            model=request_payload.get("model"),
            prompt=request_payload.get("prompt"),
            task_id=task.task_id,
            metadata_json={"suno_response": response_payload},
        )

        self.db.add(song)
        self.db.commit()

        return task

    async def generate_lyrics(self, payload: dict[str, Any]) -> SunoTask:
        request_payload = self._with_callback(payload)
        response_payload = await self.client.generate_lyrics(request_payload)
        task = self._store_task("generate_lyrics", request_payload, response_payload)

        return task

    async def call_task_endpoint(self, task_type: str, payload: dict[str, Any]) -> SunoTask:
        request_payload = SunoAPIClient._normalize_payload(self._with_callback(dict(payload))) or {}

        method_map = {
            "extend_music": self.client.extend_music,
            "upload_and_cover": self.client.upload_and_cover,
            "upload_and_extend": self.client.upload_and_extend,
            "add_instrumental": self.client.add_instrumental,
            "add_vocals": self.client.add_vocals,
            "boost_music_style": self.client.boost_music_style,
            "generate_mashup": self.client.generate_mashup,
            "replace_section": self.client.replace_section,
            "generate_persona": self.client.generate_persona,
            "create_cover": self.client.create_music_cover,
            "generate_sounds": self.client.generate_sounds,
            "get_timestamped_lyrics": self.client.get_timestamped_lyrics,
            "separate": self.client.separate,
            "convert_to_wav": self.client.convert_to_wav,
            "generate_midi": self.client.generate_midi,
            "create_video": self.client.create_video,
            "voice_validate": self.client.generate_voice_verification_phrase,
            "voice_regenerate": self.client.regenerate_voice_verification_phrase,
            "create_custom_voice": self.client.create_custom_voice,
        }

        if task_type not in method_map:
            raise ValueError(f"Unbekannter Task-Typ: {task_type}")

        response_payload = await method_map[task_type](request_payload)
        task = self._store_task(task_type, request_payload, response_payload)
        self._create_task_started_notification(task, request_payload.get("title") or request_payload.get("prompt"))

        if task_type == "generate_persona":
            self._upsert_persona_from_payload(request_payload, response_payload)

        if task_type == "create_custom_voice":
            self._upsert_voice_from_payload(request_payload, response_payload)

        if task_type == "boost_music_style":
            task.result_payload = response_payload
            task.status = _extract_status(response_payload) or "completed"
            self.db.commit()
            self.db.refresh(task)

        return task

    async def get_voice_validation_phrase(self, task_id: str) -> dict[str, Any]:
        result = await self.client.get_voice_verification_phrase(task_id)
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False)).first()
        if task:
            task.result_payload = result
            task.status = _extract_status(result) or task.status
            task.error_message = None
            self.db.commit()
        return result

    async def get_custom_voice_record(self, task_id: str) -> dict[str, Any]:
        result = await self.client.get_custom_voice_record(task_id)
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False)).first()
        if task:
            task.result_payload = result
            task.status = _extract_status(result) or task.status
            task.error_message = None
            self._upsert_voice_from_payload(task.request_payload or {}, result)
            self.db.commit()
        else:
            self._upsert_voice_from_payload({"task_id": task_id}, result)
        return result

    async def check_voice_availability(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.client.check_voice_availability(payload)


    def _create_task_started_notification(self, task: SunoTask, title: str | None = None) -> None:
        if not task or not getattr(task, "id", None):
            return
        existing = (
            self.db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == f"{task.task_type}_started",
                StatusNotification.is_deleted.is_(False),
            )
            .first()
        )
        if existing:
            return

        request_payload = task.request_payload or {}
        display_title = (
            title
            or request_payload.get("title")
            or request_payload.get("name")
            or task.task_type
            or "Suno Task"
        )
        self.db.add(StatusNotification(
            event_type=f"{task.task_type}_started",
            title=f"Gestartet: {display_title}",
            message=f"{task.task_type} · {task.status or 'RUNNING'}",
            severity="info",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task_status",
            content_id=task.id,
            target_tab="status",
            target_payload={
                "task_local_id": task.id,
                "suno_task_id": task.task_id,
                "task_type": task.task_type,
                "status": task.status or "RUNNING",
            },
        ))
        self.db.commit()

    def _create_task_status_notification(
        self,
        task: SunoTask,
        old_status: str | None,
        song: Song | None = None,
    ) -> None:
        new_status = str(task.status or "").strip().upper()
        old_status_norm = str(old_status or "").strip().upper()
        success_states = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED"}
        warning_states = {"PARTIAL_SUCCESS"}
        failure_states = {
            "FAILED",
            "ERROR",
            "CREATE_TASK_FAILED",
            "GENERATE_AUDIO_FAILED",
            "CALLBACK_EXCEPTION",
            "SENSITIVE_WORD_ERROR",
        }
        terminal = success_states | warning_states | failure_states

        if new_status not in terminal:
            return

        # Startmeldungen bleiben sonst als offene Info-Badges stehen, obwohl der
        # Task bereits fertig ist. Darum wird die passende Startmeldung beim
        # terminalen Status sauber erledigt markiert.
        started_event_type = f"{task.task_type}_started"
        started_notification = (
            self.db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == started_event_type,
                StatusNotification.is_deleted.is_(False),
            )
            .first()
        )
        if started_notification:
            started_notification.status = "done"
            started_notification.completed_at = started_notification.completed_at or utc_now_naive()
            started_notification.target_tab = "status"
            started_notification.target_payload = {
                **(started_notification.target_payload or {}),
                "task_local_id": task.id,
                "suno_task_id": task.task_id,
                "task_type": task.task_type,
                "status": new_status,
            }

        asset_rows: list[AudioAsset] = []
        if task.task_id:
            asset_rows = (
                self.db.query(AudioAsset)
                .filter(
                    AudioAsset.suno_task_id == task.task_id,
                    AudioAsset.is_deleted.is_(False),
                )
                .order_by(AudioAsset.id.asc())
                .all()
            )
        if not asset_rows and task.id:
            asset_rows = (
                self.db.query(AudioAsset)
                .filter(
                    AudioAsset.task_local_id == task.id,
                    AudioAsset.is_deleted.is_(False),
                )
                .order_by(AudioAsset.id.asc())
                .all()
            )
        first_asset = asset_rows[0] if asset_rows else None

        title_candidates = [
            getattr(first_asset, "display_title", None),
            getattr(first_asset, "title", None),
            getattr(song, "title", None),
            (task.request_payload or {}).get("title"),
            task.task_type,
        ]
        item_title = next(
            (
                str(value).strip()
                for value in title_candidates
                if value and str(value).strip()
            ),
            "Suno Task",
        )

        ok = new_status in success_states
        warn = new_status in warning_states
        failed = new_status in failure_states
        severity = "success" if ok else "warning" if warn else "error"
        state_label = "fertig" if ok else "teilweise fertig" if warn else "fehlgeschlagen"

        audio_asset_ids = [int(asset.id) for asset in asset_rows if getattr(asset, "id", None)]
        target_payload = {
            "task_local_id": task.id,
            "suno_task_id": task.task_id,
            "task_type": task.task_type,
            "status": new_status,
            "audio_asset_id": first_asset.id if first_asset else None,
            "primary_audio_asset_id": first_asset.id if first_asset else None,
            "audio_asset_ids": audio_asset_ids,
            "song_id": song.id if song else None,
            "project_id": first_asset.project_id if first_asset else (song.project_id if song else None),
        }

        existing = (
            self.db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == "task_completed",
                StatusNotification.is_deleted.is_(False),
            )
            .first()
        )

        if existing:
            # Bestehende Abschlussmeldung nie im alten Info-/Fehlerzustand lassen.
            existing.title = f"{item_title} ist {state_label}"
            existing.message = f"{task.task_type} · {new_status}"
            existing.severity = severity
            existing.status = "unread" if old_status_norm != new_status else (existing.status or "unread")
            existing.task_local_id = task.id
            existing.suno_task_id = task.task_id
            existing.content_type = "audio" if first_asset and ok else "task_status"
            existing.content_id = first_asset.id if first_asset and ok else task.id
            existing.target_tab = "library" if first_asset and ok else "status"
            existing.target_payload = target_payload
            existing.completed_at = existing.completed_at or utc_now_naive()
            return

        notification = StatusNotification(
            event_type="task_completed",
            title=f"{item_title} ist {state_label}",
            message=f"{task.task_type} · {new_status}",
            severity=severity,
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="audio" if first_asset and ok else "task_status",
            content_id=first_asset.id if first_asset and ok else task.id,
            target_tab="library" if first_asset and ok else "status",
            target_payload=target_payload,
            completed_at=utc_now_naive(),
        )

        self.db.add(notification)

    def _attach_import_result(
        self,
        task: SunoTask,
        *,
        already_imported: bool,
        import_status: str,
        import_message: str,
    ) -> SunoTask:
        setattr(task, "already_imported", already_imported)
        setattr(task, "import_status", import_status)
        setattr(task, "import_message", import_message)
        return task

    def _find_existing_imported_task(self, task_id: str) -> SunoTask | None:
        existing_task = (
            self.db.query(SunoTask)
            .filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False))
            .order_by(SunoTask.id.desc())
            .first()
        )
        if existing_task:
            if self._soft_delete_orphaned_import_task(existing_task):
                return None
            return existing_task

        existing_song = (
            self.db.query(Song)
            .filter(Song.task_id == task_id, Song.is_deleted.is_(False))
            .order_by(Song.id.desc())
            .first()
        )
        existing_asset = (
            self.db.query(AudioAsset)
            .filter(AudioAsset.suno_task_id == task_id, AudioAsset.is_deleted.is_(False))
            .order_by(AudioAsset.id.desc())
            .first()
        )

        if not existing_song and not existing_asset:
            return None

        recovered = SunoTask(
            task_id=task_id,
            task_type="imported_external",
            status="IMPORTED_ALREADY_EXISTS",
            request_payload={
                "source": "manual_sunoapi_import",
                "task_id": task_id,
                "duplicate_detected": True,
                "song_id": existing_song.id if existing_song else None,
                "audio_asset_id": existing_asset.id if existing_asset else None,
            },
            response_payload={
                "source": "manual_sunoapi_import",
                "taskId": task_id,
                "duplicate_detected": True,
            },
        )
        self.db.add(recovered)
        self.db.commit()
        self.db.refresh(recovered)
        return recovered

    def _sync_task_request_payload_to_related_media(self, task: SunoTask) -> bool:
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        if not request_payload:
            return False

        changed = False
        songs = []
        if task.task_id:
            songs = self.db.query(Song).filter(Song.task_id == task.task_id, Song.is_deleted.is_(False)).all()
        for song in songs:
            metadata = dict(song.metadata_json or {}) if isinstance(song.metadata_json, dict) else {}
            existing_request = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
            merged_request = {**existing_request, **request_payload}
            if metadata.get("request_payload") != merged_request:
                metadata["request_payload"] = merged_request
                song.metadata_json = metadata
                self.db.add(song)
                flag_modified(song, "metadata_json")
                changed = True

        asset_query = self.db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False))
        if task.id and task.task_id:
            assets = asset_query.filter((AudioAsset.task_local_id == task.id) | (AudioAsset.suno_task_id == task.task_id)).all()
        elif task.id:
            assets = asset_query.filter(AudioAsset.task_local_id == task.id).all()
        elif task.task_id:
            assets = asset_query.filter(AudioAsset.suno_task_id == task.task_id).all()
        else:
            assets = []
        for asset in assets:
            metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
            existing_request = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
            merged_request = {**existing_request, **request_payload}
            if metadata.get("request_payload") != merged_request:
                metadata["request_payload"] = merged_request
                asset.metadata_json = metadata
                self.db.add(asset)
                flag_modified(asset, "metadata_json")
                changed = True
        return changed

    def _repair_imported_task_generation_options(self, task: SunoTask) -> bool:
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        merged_request = _merge_generation_options_into_request(request_payload, task.result_payload, task.response_payload)
        changed = merged_request != request_payload
        if changed:
            task.request_payload = merged_request
            self.db.add(task)
            flag_modified(task, "request_payload")
        return self._sync_task_request_payload_to_related_media(task) or changed

    def _soft_delete_orphaned_import_task(self, task: SunoTask) -> bool:
        task_id = str(task.task_id or "").strip()
        if not task_id:
            return False
        active_status = str(task.status or "").strip().upper()
        if active_status in IMPORT_DEDUP_BLOCKING_ACTIVE_STATUSES:
            return False
        existing_song = (
            self.db.query(Song.id)
            .filter(Song.task_id == task_id, Song.is_deleted.is_(False))
            .first()
        )
        existing_asset = (
            self.db.query(AudioAsset.id)
            .filter(AudioAsset.suno_task_id == task_id, AudioAsset.is_deleted.is_(False))
            .first()
        )
        if existing_song or existing_asset:
            return False
        task.is_deleted = True
        task.deleted_at = utc_now_naive()
        task.deleted_reason = "Verwaiste Task-ID beim Re-Import freigegeben"
        self.db.flush()
        return True

    def _create_import_duplicate_notification(self, task: SunoTask) -> None:
        existing = (
            self.db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == "manual_sunoapi_import_duplicate",
                StatusNotification.status != "done",
                StatusNotification.is_deleted.is_(False),
            )
            .first()
        )
        if existing:
            return

        notification = StatusNotification(
            event_type="manual_sunoapi_import_duplicate",
            title="Suno-Task wurde bereits importiert",
            message=f"Task-ID {task.task_id} ist bereits in der Datenbank vorhanden. Es wurde kein zweiter Song und kein zweites AudioAsset erstellt.",
            severity="info",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task",
            content_id=task.id,
            target_tab="status",
            target_payload={
                "task_local_id": task.id,
                "suno_task_id": task.task_id,
                "already_imported": True,
            },
        )
        self.db.add(notification)

    async def _fetch_external_task_details(self, task_id: str, task_type: str) -> dict[str, Any]:
        if task_type == "generate_lyrics":
            return await self.client.get_lyrics_details(task_id)
        if task_type == "separate":
            return await self.client.get_vocal_separation_details(task_id)
        if task_type == "convert_to_wav":
            return await self.client.get_wav_details(task_id)
        if task_type == "generate_midi":
            return await self.client.get_midi_details(task_id)
        if task_type == "create_video":
            return await self.client.get_video_details(task_id)
        if task_type == "create_cover":
            return await self.client.get_cover_details(task_id)
        if task_type == "create_custom_voice":
            return await self.client.get_custom_voice_record(task_id)
        return await self.client.get_details(task_id)

    async def _refresh_existing_imported_task_details(self, task: SunoTask, *, task_type: str, base_request_payload: dict[str, Any]) -> bool:
        if not task.task_id:
            return False
        details = await self._fetch_external_task_details(str(task.task_id), task_type)
        existing_request = task.request_payload if isinstance(task.request_payload, dict) else {}
        merged_request = {**existing_request, **{key: value for key, value in base_request_payload.items() if value is not None}}
        merged_request = _merge_generation_options_into_request(merged_request, details, task.response_payload)

        changed = False
        if task.result_payload != details:
            task.result_payload = details
            flag_modified(task, "result_payload")
            changed = True
        if task.request_payload != merged_request:
            task.request_payload = merged_request
            flag_modified(task, "request_payload")
            changed = True
        next_status = _extract_status(details)
        if next_status and task.status != next_status:
            task.status = next_status
            changed = True
        source_created_at = extract_source_created_at(details)
        if source_created_at and task.created_at and task.created_at > source_created_at:
            task.created_at = source_created_at
            changed = True
        if changed:
            task.error_message = None
            self.db.add(task)
        return self._sync_task_request_payload_to_related_media(task) or changed

    async def repair_imported_task_generation_options_from_provider(self, *, limit: int = 40) -> int:
        """Backfill old manual imports whose stored result payload lacks Suno request options."""
        repaired = 0
        any_changed = False
        rows = (
            self.db.query(SunoTask)
            .filter(SunoTask.task_id.isnot(None), SunoTask.is_deleted.is_(False))
            .order_by(SunoTask.updated_at.desc(), SunoTask.id.desc())
            .limit(max(1, int(limit or 40)))
            .all()
        )
        for task in rows:
            request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
            if (
                request_payload.get("generation_options_provider_checked")
                and request_payload.get("generation_options_provider_check_version") == GENERATION_OPTIONS_PROVIDER_CHECK_VERSION
            ):
                continue
            missing_before = _missing_imported_generation_option_keys(request_payload)
            if not missing_before:
                continue
            task_type = str(request_payload.get("task_type") or task.task_type or "generate_music")
            if task_type in LOCAL_APP_TASK_TYPES or task_type == "generate_music_opencli":
                continue
            try:
                changed = await self._refresh_existing_imported_task_details(task, task_type=task_type, base_request_payload=request_payload)
                request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
                missing_after = _missing_imported_generation_option_keys(request_payload)
                next_request_payload = dict(request_payload)
                next_request_payload["generation_options_provider_checked"] = True
                next_request_payload["generation_options_provider_checked_at"] = utc_now_naive().isoformat()
                next_request_payload["generation_options_provider_check_version"] = GENERATION_OPTIONS_PROVIDER_CHECK_VERSION
                if task.request_payload != next_request_payload:
                    task.request_payload = next_request_payload
                    flag_modified(task, "request_payload")
                    self.db.add(task)
                    changed = True
                if self._sync_task_request_payload_to_related_media(task):
                    changed = True
                if changed:
                    any_changed = True
                if len(missing_after) < len(missing_before):
                    repaired += 1
            except Exception:
                continue
        if any_changed:
            self.db.flush()
        return repaired

    async def import_external_task(self, payload: dict[str, Any]) -> SunoTask:
        task_id = str(payload.get("task_id") or payload.get("taskId") or "").strip()
        task_type = str(payload.get("task_type") or "generate_music").strip()
        cache_audio = bool(payload.get("cache_audio", True))

        if not task_id:
            raise ValueError("Task-ID fehlt.")

        request_payload = {
            "source": "manual_sunoapi_import",
            "task_id": task_id,
            "task_type": task_type,
            "title": payload.get("title") or None,
            "prompt": payload.get("prompt") or None,
            "style": payload.get("style") or None,
            "model": payload.get("model") or None,
        }

        existing = self._find_existing_imported_task(task_id)

        if existing is not None:
            try:
                await self._refresh_existing_imported_task_details(existing, task_type=task_type, base_request_payload=request_payload)
            except Exception:
                self._repair_imported_task_generation_options(existing)
            self._create_import_duplicate_notification(existing)
            self.db.commit()
            self.db.refresh(existing)
            return self._attach_import_result(
                existing,
                already_imported=True,
                import_status="already_imported",
                import_message="Dieser Suno-Task ist bereits importiert. Es wurde nichts doppelt erstellt.",
            )

        details = await self._fetch_external_task_details(task_id, task_type)

        request_payload = _merge_generation_options_into_request(request_payload, details)

        source_created_at = extract_source_created_at(details)
        extracted_status = _extract_status(details)
        if not extracted_status and collect_audio_candidates(details):
            extracted_status = "SUCCESS"

        old_status = existing.status if existing else None

        if existing is None:
            task = SunoTask(
                task_id=task_id,
                task_type=task_type,
                status=extracted_status or "IMPORTED",
                request_payload=request_payload,
                response_payload={
                    "source": "manual_sunoapi_import",
                    "taskId": task_id,
                    "taskType": task_type,
                },
                result_payload=details,
            )
            if source_created_at:
                task.created_at = source_created_at
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)
        else:
            task = existing
            merged_request = task.request_payload if isinstance(task.request_payload, dict) else {}
            merged_request.update({key: value for key, value in request_payload.items() if value is not None})
            task.task_type = task.task_type or task_type
            task.request_payload = merged_request
            task.response_payload = task.response_payload or {
                "source": "manual_sunoapi_import",
                "taskId": task_id,
                "taskType": task_type,
            }
            task.result_payload = details
            task.status = extracted_status or task.status or "IMPORTED"
            if source_created_at and task.created_at and task.created_at > source_created_at:
                task.created_at = source_created_at
            task.error_message = None
            self.db.commit()
            self.db.refresh(task)

        song = self._upsert_song_from_task(task)
        self._sync_task_request_payload_to_related_media(task)

        if task.task_type == "create_custom_voice":
            self._upsert_voice_from_payload(task.request_payload or {}, task.result_payload or {})

        if cache_audio:
            await self._cache_audio_if_configured(task, song=song)
        else:
            try:
                AudioAssetMaterializationService(self.db).materialize_task(task, song=song, force=True)
            except Exception as exc:
                task.error_message = f"AudioAsset-Materialisierung fehlgeschlagen: {exc}"
                self.db.commit()
            try:
                await CoverCacheService(self.db).cache_task_covers(task, song=song)
            except Exception as exc:
                task.error_message = f"Cover-Cache-Fehler: {exc}"
                self.db.commit()

        self._sync_task_request_payload_to_related_media(task)
        self._create_task_status_notification(task, old_status, song=song)
        self.db.commit()
        self.db.refresh(task)
        return self._attach_import_result(
            task,
            already_imported=False,
            import_status="imported",
            import_message="Suno-Task wurde importiert und lokal abgelegt.",
        )


    async def refresh_task(self, task: SunoTask) -> SunoTask:
        old_status = task.status

        # Lokale App-Tasks besitzen keine externe Suno-Task-ID und dürfen
        # niemals gegen die SunoAPI geprüft werden. Das betrifft u.a.
        # Replicate-Cover, SRT, Stems und lokale WAV-Konvertierung.
        if task.task_type in LOCAL_APP_TASK_TYPES or (isinstance(task.request_payload, dict) and task.request_payload.get("local_task")):
            return task
        if task.task_type == "generate_music_opencli":
            # OpenCLI ist ein lokaler Background-Provider. Er darf nicht gegen die
            # externe SunoAPI geprüft werden. Falls der Background-Task bereits
            # Resultate/Dateien geschrieben hat, kann der OpenCLI-Service den Status
            # kontrolliert finalisieren; ansonsten bleibt der aktuelle Status erhalten.
            from app.services.opencli_provider_service import OpenCliProviderService
            return OpenCliProviderService(self.db).refresh_generation_task(task)

        if not task.task_id:
            task.task_id = _extract_task_id(task.response_payload) or _extract_task_id(task.result_payload)
            if task.task_id:
                self.db.commit()
                self.db.refresh(task)

        if not task.task_id:
            if task.task_type == "generate_persona":
                task.status = "completed"
                self._upsert_persona_from_payload(task.request_payload or {}, task.response_payload or {})
                self.db.commit()
                self.db.refresh(task)
                return task

            raise ValueError("Task besitzt keine externe Suno Task-ID.")

        if task.task_type == "generate_lyrics":
            details = await self.client.get_lyrics_details(task.task_id)
        elif task.task_type == "separate":
            details = await self.client.get_vocal_separation_details(task.task_id)
        elif task.task_type == "convert_to_wav":
            details = await self.client.get_wav_details(task.task_id)
        elif task.task_type == "generate_midi":
            details = await self.client.get_midi_details(task.task_id)
        elif task.task_type == "create_video":
            details = await self.client.get_video_details(task.task_id)
        elif task.task_type == "voice_validate" or task.task_type == "voice_regenerate":
            details = await self.client.get_voice_verification_phrase(task.task_id)
        elif task.task_type == "create_custom_voice":
            details = await self.client.get_custom_voice_record(task.task_id)
        elif task.task_type == "create_cover":
            details = await self.client.get_cover_details(task.task_id)
        else:
            details = await self.client.get_details(task.task_id)

        task.result_payload = details
        task.status = _extract_status(details) or task.status
        task.heartbeat_at = utc_now_naive()
        if str(task.status or "").upper() in {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "FAILED", "ERROR"}:
            task.completed_at = task.completed_at or utc_now_naive()
        task.error_message = None

        self.db.commit()
        self.db.refresh(task)

        song = self._upsert_song_from_task(task)

        if task.task_type == "create_custom_voice":
            self._upsert_voice_from_payload(task.request_payload or {}, task.result_payload or {})

        await self._cache_audio_if_configured(task, song=song)

        self._create_task_status_notification(task, old_status, song=song)

        self.db.commit()
        self.db.refresh(task)

        return task

    async def refresh_pending_tasks(self, limit: int = 20) -> list[SunoTask]:
        pending_statuses = [
            "SUBMITTED",
            "PENDING",
            "PROCESSING",
            "RUNNING",
            "QUEUED",
            "CREATED",
            "FIRST_SUCCESS",
            "TEXT_SUCCESS",
        ]

        candidates = (
            self.db.query(SunoTask)
            .filter(
                SunoTask.is_deleted.is_(False),
                func.upper(SunoTask.status).in_(pending_statuses),
            )
            .order_by(SunoTask.created_at.desc())
            .limit(limit)
            .all()
        )

        refreshed: list[SunoTask] = []

        for task in candidates:
            if task.task_type in LOCAL_APP_TASK_TYPES or (isinstance(task.request_payload, dict) and task.request_payload.get("local_task")):
                refreshed.append(task)
                continue
            try:
                refreshed.append(await self.refresh_task(task))
            except Exception as exc:
                message = str(exc)
                task.error_message = message
                if "keine externe Suno Task-ID" in message or "keine externe" in message:
                    task.status = "FAILED"
                self.db.commit()
                self.db.refresh(task)
                refreshed.append(task)

        return refreshed

    def list_tasks(self, limit: int = 250) -> list[SunoTask]:
        # Aktive lokale Batch-/SRT-/Stem-Tasks müssen immer in der Statusseite
        # sichtbar sein, auch wenn bereits viele ältere Tasks existieren. Darum
        # werden aktive Tasks zuerst separat geholt und anschließend mit den
        # neuesten Tasks dedupliziert.
        active_statuses = [
            "SUBMITTED",
            "PENDING",
            "PROCESSING",
            "RUNNING",
            "QUEUED",
            "CREATED",
            "FIRST_SUCCESS",
            "TEXT_SUCCESS",
        ]
        active_rows = (
            self.db.query(SunoTask)
            .filter(
                SunoTask.is_deleted.is_(False),
                func.upper(SunoTask.status).in_(active_statuses),
            )
            .order_by(SunoTask.created_at.desc())
            .limit(max(limit, 250))
            .all()
        )
        recent_rows = (
            self.db.query(SunoTask)
            .filter(SunoTask.is_deleted.is_(False))
            .order_by(SunoTask.created_at.desc())
            .limit(limit)
            .all()
        )
        merged: list[SunoTask] = []
        seen: set[int] = set()
        for row in [*active_rows, *recent_rows]:
            if row.id in seen:
                continue
            merged.append(row)
            seen.add(row.id)
        return merged[: max(limit, len(active_rows))]

    def list_songs(self, limit: int = 250) -> list[Song]:
        safe_limit = max(1, min(int(limit or 250), 1000))
        # /api/music/songs bleibt read-only, sortiert aber stabil nach dem
        # originalen Suno/SunoAPI-Erstelldatum aus metadata_json, wenn vorhanden.
        # So entspricht die API-Liste der fachlichen Reihenfolge "neueste zuerst"
        # und nicht nur der lokalen SQLite-Einfügezeit.
        rows = (
            self.db.query(Song)
            .filter(Song.is_deleted.is_(False))
            .order_by(Song.created_at.desc(), Song.id.desc())
            .limit(safe_limit * 3)
            .all()
        )
        rows.sort(key=lambda song: (song_sort_datetime(song), song.id or 0), reverse=True)
        return rows[:safe_limit]
